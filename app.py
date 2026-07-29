# ~/CombinedNiftyNewsApp/app.py
import os
import logging
import threading
from flask import Flask, render_template, request, jsonify, session as flask_session
from datetime import datetime, timedelta, timezone
import json
import time
from sqlalchemy.orm import Session
import pandas as pd
import yfinance as yf

# Project-specific utils
from utils import gemini_utils, sentiment_analyzer, db_crud, newsapi_helpers
from utils.database_models import SessionLocal, create_db_and_tables, ScrapedArticle

import config # Your project's config.py

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

# --- Logging Setup ---
# (Your existing comprehensive logging setup)
logging.basicConfig(
    level=logging.DEBUG, # Set to INFO for less verbosity in production
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d (%(funcName)s)] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "app.log"))
    ]
)
logger = logging.getLogger(__name__) # Main app logger
logging.getLogger("werkzeug").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("nltk").setLevel(logging.INFO)
logging.getLogger("yfinance").setLevel(logging.WARNING) # yfinance can be verbose
logging.getLogger("fake_useragent").setLevel(logging.WARNING)


# --- Database ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- API Key Management ---
def get_api_keys_from_session_or_config():
    gemini_key = flask_session.get('gemini_key_sess', config.GEMINI_API_KEY)
    newsapi_key = flask_session.get('newsapi_key_sess', config.NEWSAPI_ORG_API_KEY)

    is_gemini_valid = bool(gemini_key and gemini_key != config.GEMINI_API_KEY_PLACEHOLDER)
    is_newsapi_valid = bool(newsapi_key and newsapi_key != config.NEWSAPI_ORG_API_KEY_PLACEHOLDER)

    logger.debug(
        f"API Keys - Gemini Valid: {is_gemini_valid} (Key ending: ...{gemini_key[-5:] if gemini_key and len(gemini_key) > 5 else 'N/A'}), "
        f"NewsAPI Valid: {is_newsapi_valid} (Key ending: ...{newsapi_key[-5:] if newsapi_key and len(newsapi_key) > 5 else 'N/A'})"
    )
    return {
        'gemini': gemini_key, 'newsapi': newsapi_key,
        'gemini_is_valid': is_gemini_valid, 'newsapi_is_valid': is_newsapi_valid
    }

# --- On-demand coverage top-up (Tier C: NewsAPI, budgeted) ---
def trigger_coverage_topup(target_type, target_name, append_log_local):
    """
    Fire-and-forget background top-up when the DB is thin for a requested
    target. The current request still answers instantly from whatever the DB
    has; by the time the user re-runs (~a minute later), fresh articles are in.
    Budget-safe: ingestion.ensure_* no-ops instantly if coverage is fine or
    the daily NewsAPI budget is exhausted.
    """
    try:
        import ingestion
        fn = ingestion.ensure_sector_coverage if target_type == "sector" \
            else ingestion.ensure_stock_coverage
        threading.Thread(target=fn, args=(target_name,), daemon=True,
                         name=f"topup-{target_name}").start()
        append_log_local(
            f"Thin coverage for '{target_name}' -- background top-up started; "
            f"re-run analysis in about a minute for fresh articles.", "INFO")
    except Exception as e:
        logger.error(f"Could not start coverage top-up for '{target_name}': {e}")

# --- UI Log Helper ---
def setup_local_logger(ui_log_list):
    def append_log_local(message, level='INFO'):
         timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
         level_upper = level.upper()
         entry = {'timestamp': timestamp, 'message': str(message), 'level': level_upper}
         ui_log_list.append(entry)
         if level_upper == 'ERROR': logger.error(f"UI_LOG_RELAY: {message}")
         elif level_upper == 'WARNING': logger.warning(f"UI_LOG_RELAY: {message}")
         else: logger.info(f"UI_LOG_RELAY: {message}")
    return append_log_local

# --- Date Parsing Helper ---
def robust_date_parse(date_str):
     if not date_str: return None
     for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y'): # Add more formats if needed
         try: return datetime.strptime(date_str, fmt).date()
         except (ValueError, TypeError): continue
     logger.warning(f"Could not parse date string from UI: '{date_str}' with known formats.")
     return None

def parse_date_for_google_search(date_obj):
    if not date_obj: return None
    return date_obj.strftime('%m/%d/%Y') # MM/DD/YYYY for Google tbs parameter

# === ROUTES ===
@app.route('/')
def index_page():
    actual_system_today = datetime.now(timezone.utc).date()
    one_month_ago = actual_system_today - timedelta(days=29) # Default for 30-day range
    sector_config = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG
    context = {
        'sector_options': sorted(list(sector_config.keys())), # Sort for better UI
        'system_actual_today': actual_system_today.strftime('%Y-%m-%d'),
        'default_end_date': actual_system_today.strftime('%Y-%m-%d'),
        'one_month_ago_date': one_month_ago.strftime('%Y-%m-%d'),
        'sector_stock_config_json': json.dumps({
            sector: sorted(list(details.get("stocks", {}).keys()))
            for sector, details in sector_config.items()
        })
    }
    return render_template('index.html', **context)

@app.route('/api/update-api-keys', methods=['POST'])
def update_api_keys_route():
    data = request.json
    log_updates = []
    if 'gemini_key' in data and data['gemini_key'].strip():
        flask_session['gemini_key_sess'] = data['gemini_key']
        log_updates.append("Gemini key updated in session.")
    if 'newsapi_key' in data and data['newsapi_key'].strip():
        flask_session['newsapi_key_sess'] = data['newsapi_key']
        log_updates.append("NewsAPI key updated in session.")

    if not log_updates:
        return jsonify({"message": "No API keys provided to update."}), 400
    logger.info(f"Session API Keys updated: {'; '.join(log_updates)}")
    return jsonify({"message": "Session API keys processed."})

def process_articles_for_llm(articles_list, target_name_for_log, db_session: Session, source_type="db"):
    processed_list = []
    if not articles_list: return processed_list

    for art_data in articles_list:
        content_to_analyze = None
        uri = None
        pub_date_str = 'N/A'
        source_name = 'N/A'
        vader_s = None
        db_id = None

        if source_type == "db" and isinstance(art_data, ScrapedArticle):
            if not art_data.article_text:
                logger.debug(f"Skipping DB article (no text): {art_data.url} for {target_name_for_log}")
                continue
            content_to_analyze = art_data.article_text
            uri = art_data.url
            pub_date_str = art_data.publication_date.strftime('%Y-%m-%d') if art_data.publication_date else 'N/A'
            source_name = art_data.source_domain or 'DB Scraped'
            vader_s = art_data.vader_score
            db_id = art_data.id
            if vader_s is None and content_to_analyze: # Calculate and store if missing
                vader_s = sentiment_analyzer.get_vader_sentiment_score(content_to_analyze)
                db_crud.update_article_sentiment_scores(db_session, article_url=uri, vader_score=vader_s)

        elif source_type == "newsapi" and isinstance(art_data, dict):
            content_to_analyze = art_data.get('content')
            if not content_to_analyze:
                logger.debug(f"Skipping NewsAPI article (no content): {art_data.get('uri')} for {target_name_for_log}")
                continue
            uri = art_data.get('uri')
            pub_date_str = art_data.get('date', 'N/A')
            source_name = art_data.get('source', 'NewsAPI.org')
            vader_s = art_data.get('vader_score') # Should be pre-calculated by newsapi_helpers

        if content_to_analyze and uri:
            processed_list.append({
                'content': content_to_analyze, 'date': pub_date_str, 'uri': uri,
                'source': source_name, 'vader_score': vader_s, 'db_id': db_id
            })
    return processed_list

@app.route('/api/sector-analysis', methods=['POST'])
def perform_sector_analysis_route():
    form_data = request.json
    logger.info(f"Batch Sector Analysis Request: {form_data}")
    ui_log_messages = []
    append_log_local = setup_local_logger(ui_log_messages)
    db: Session = next(get_db())
    current_api_keys = get_api_keys_from_session_or_config()
    results_payload = []
    user_facing_errors = []

    selected_sectors = form_data.get('selected_sectors')
    if not selected_sectors or not isinstance(selected_sectors, list) or not all(selected_sectors):
        user_facing_errors.append("Please select at least one valid sector.")
    if not current_api_keys.get('gemini_is_valid'):
        user_facing_errors.append("Gemini API key is not configured or is a placeholder.")

    start_date_str = form_data.get('start_date')
    end_date_str = form_data.get('end_date')
    if not start_date_str or not end_date_str:
        user_facing_errors.append("Start and End dates are required.")

    if user_facing_errors:
        logger.warning(f"Batch Sector Analysis validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results': []}), 400

    query_start_date = robust_date_parse(start_date_str)
    query_end_date = robust_date_parse(end_date_str)
    actual_today_server = datetime.now(timezone.utc).date()

    if not query_start_date or not query_end_date:
        user_facing_errors.append("Invalid Start or End date format.")
    elif query_start_date > query_end_date:
        user_facing_errors.append("Start date cannot be after end date.")
    if user_facing_errors: # Re-check after date parsing
        logger.warning(f"Batch Sector Analysis date validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results': []}), 400

    query_end_date = min(query_end_date, actual_today_server) # Cap end date

    try:
        max_articles_llm = int(form_data.get('sector_max_articles', 5)) # This key comes from JS
        if max_articles_llm < 1: max_articles_llm = 1
    except ValueError:
        user_facing_errors.append("Invalid number for Max Articles.")
        logger.warning(f"Batch Sector Analysis max articles parsing error.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results': []}), 400

    custom_prompt = form_data.get('sector_custom_prompt', '')
    llm_context_range_str = f"{query_start_date.strftime('%Y-%m-%d')} to {query_end_date.strftime('%Y-%m-%d')}"
    append_log_local(f"Batch Sector Analysis - Dates: {llm_context_range_str}, Max articles/sector for LLM: {max_articles_llm}", "INFO")

    for sector_name in selected_sectors:
        append_log_local(f"--- Processing SECTOR: {sector_name} ---", "INFO")
        sector_cfg = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(sector_name, {})
        db_keywords = [sector_name] + sector_cfg.get("newsapi_keywords", [])[:3]

        db_articles = db_crud.get_articles_for_analysis(db, query_start_date, query_end_date, list(set(db_keywords)), limit=max_articles_llm * 2)

        # Thin coverage? Kick off a budgeted background NewsAPI top-up for this
        # sector (no-ops if budget exhausted). Current response still uses what
        # the DB has right now.
        if len(db_articles) < max_articles_llm:
            trigger_coverage_topup("sector", sector_name, append_log_local)

        articles_for_llm = process_articles_for_llm(db_articles, sector_name, db, source_type="db")[:max_articles_llm]

        sector_error, gemini_result, vader_avg, vader_label = None, None, 0.0, "Neutral"
        if not articles_for_llm:
            sector_error = f"No relevant articles found in DB for sector '{sector_name}' for LLM."
            append_log_local(sector_error, "WARNING")
        else:
            gemini_result, gemini_err = gemini_utils.analyze_news_with_gemini(
                current_api_keys['gemini'], [art['content'] for art in articles_for_llm],
                sector_name, llm_context_range_str, custom_prompt, append_log_local, target_type="sector"
            )
            if gemini_err: sector_error = gemini_err

        all_vader_scores = [art['vader_score'] for art in process_articles_for_llm(db_articles, sector_name, db, source_type="db") if art.get('vader_score') is not None] # Use all fetched for VADER avg
        if all_vader_scores:
            vader_avg = sentiment_analyzer.get_average_vader_score(all_vader_scores)
            vader_label = sentiment_analyzer.get_sentiment_label_from_score(vader_avg)

        results_payload.append({
            'sector_name': sector_name, 'llm_context_date_range': llm_context_range_str,
            'num_articles_for_llm_sector': len(articles_for_llm),
            'gemini_analysis_sector': gemini_result, 'error_message_sector': sector_error,
            'avg_vader_score_sector': vader_avg, 'vader_sentiment_label_sector': vader_label,
            'constituent_stocks': sorted(list(sector_cfg.get("stocks", {}).keys()))
        })
    append_log_local("--- Batch Sector analysis finished. ---", "INFO")
    return jsonify({'error': False, 'messages': ["Batch Sector analysis complete."], 'results': results_payload, 'logs': ui_log_messages})

@app.route('/api/stock-analysis', methods=['POST'])
def perform_sub_stock_analysis_route():
    form_data = request.json
    logger.info(f"Sub-Stock Analysis Request: {form_data}")
    ui_log_messages = []
    append_log_local = setup_local_logger(ui_log_messages)
    db: Session = next(get_db())
    current_api_keys = get_api_keys_from_session_or_config()
    results_payload = []
    user_facing_errors = []

    sector_name = form_data.get('sector_name')
    selected_stocks = form_data.get('selected_stocks')
    start_date_str = form_data.get('start_date') # From main form, passed by JS
    end_date_str = form_data.get('end_date')     # From main form, passed by JS

    if not sector_name or not selected_stocks or not isinstance(selected_stocks, list) or not all(selected_stocks):
        user_facing_errors.append("Sector name and at least one stock selection are required.")
    if not current_api_keys.get('gemini_is_valid'):
        user_facing_errors.append("Gemini API key is not configured or is a placeholder.")
    if not start_date_str or not end_date_str:
        user_facing_errors.append("Start and End dates are required.")

    if user_facing_errors:
        logger.warning(f"Sub-Stock Analysis validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results_stocks': []}), 400

    query_start_date = robust_date_parse(start_date_str)
    query_end_date = robust_date_parse(end_date_str)
    actual_today_server = datetime.now(timezone.utc).date()

    if not query_start_date or not query_end_date:
        user_facing_errors.append("Invalid Start or End date format for sub-stock analysis.")
    elif query_start_date > query_end_date:
        user_facing_errors.append("Start date cannot be after end date for sub-stock analysis.")
    if user_facing_errors:
        logger.warning(f"Sub-Stock Analysis date validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results_stocks': []}), 400

    query_end_date = min(query_end_date, actual_today_server)

    try:
        max_articles_llm = int(form_data.get('stock_max_articles', 3)) # This key comes from JS
        if max_articles_llm < 1: max_articles_llm = 1
    except ValueError:
        user_facing_errors.append("Invalid number for Max Articles (Stock).")
        logger.warning(f"Sub-Stock Analysis max articles parsing error.")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages, 'results_stocks': []}), 400

    custom_prompt = form_data.get('custom_prompt', '') # This key comes from JS
    llm_context_range_str = f"{query_start_date.strftime('%Y-%m-%d')} to {query_end_date.strftime('%Y-%m-%d')}"
    append_log_local(f"Sub-Stock analysis for '{sector_name}' stocks. Dates: {llm_context_range_str}, Max articles/stock: {max_articles_llm}", "INFO")

    sector_cfg = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(sector_name, {})
    stock_keywords_map = sector_cfg.get("stocks", {})

    for stock_name in selected_stocks:
        append_log_local(f"--- Processing STOCK: {stock_name} (Sector: {sector_name}) ---", "INFO")
        db_keywords = [stock_name] + stock_keywords_map.get(stock_name, [])[:2]

        db_articles = db_crud.get_articles_for_analysis(db, query_start_date, query_end_date, list(set(db_keywords)), limit=max_articles_llm * 2)

        # Thin coverage? Budgeted background NewsAPI top-up for this stock.
        if len(db_articles) < max_articles_llm:
            trigger_coverage_topup("stock", stock_name, append_log_local)

        articles_for_llm = process_articles_for_llm(db_articles, stock_name, db, source_type="db")[:max_articles_llm]

        stock_error, gemini_result, vader_avg, vader_label = None, None, 0.0, "Neutral"
        if not articles_for_llm:
            stock_error = f"No relevant articles found in DB for stock '{stock_name}' for LLM."
            append_log_local(stock_error, "WARNING")
        else:
            gemini_result, gemini_err = gemini_utils.analyze_news_with_gemini(
                current_api_keys['gemini'], [art['content'] for art in articles_for_llm],
                stock_name, llm_context_range_str, custom_prompt, append_log_local, target_type="stock"
            )
            if gemini_err: stock_error = gemini_err
            if gemini_result: # Store LLM analysis for the articles used in this batch
                for art_item in articles_for_llm:
                    if art_item.get('db_id'): # Only for DB articles
                        db_crud.update_article_sentiment_scores(db, article_url=art_item['uri'],
                            llm_sentiment_score=gemini_result.get('sentiment_score_llm'),
                            llm_sentiment_label=gemini_result.get('overall_sentiment'),
                            llm_analysis_json=json.dumps(gemini_result), # Store aggregated analysis for this stock batch
                            related_sector=sector_name, related_stock=stock_name)

        all_vader_scores = [art['vader_score'] for art in process_articles_for_llm(db_articles, stock_name, db, source_type="db") if art.get('vader_score') is not None]
        if all_vader_scores:
            vader_avg = sentiment_analyzer.get_average_vader_score(all_vader_scores)
            vader_label = sentiment_analyzer.get_sentiment_label_from_score(vader_avg)

        results_payload.append({
            'stock_name': stock_name, 'llm_context_date_range': llm_context_range_str,
            'num_articles_for_llm_stock': len(articles_for_llm),
            'gemini_analysis_stock': gemini_result, 'error_message_stock': stock_error,
            'avg_vader_score_stock': vader_avg, 'vader_sentiment_label_stock': vader_label
        })
    append_log_local(f"--- Sub-Stock analysis for sector '{sector_name}' finished. ---", "INFO")
    return jsonify({'error': False, 'messages': [f"Stock analysis for '{sector_name}' complete."], 'results_stocks': results_payload, 'sector_name': sector_name, 'logs': ui_log_messages})

@app.route('/api/adhoc-analysis-scrape', methods=['POST'])
def adhoc_analysis_scrape_route():
    form_data = request.json
    logger.info(f"Ad-hoc Analysis/Scrape Request: {form_data}")
    ui_log_messages = []
    append_log_local = setup_local_logger(ui_log_messages)
    db: Session = next(get_db())
    current_api_keys = get_api_keys_from_session_or_config()
    user_facing_errors = []

    target_name = form_data.get('target_name', '').strip()
    target_type = form_data.get('target_type', 'stock')
    start_date_str = form_data.get('start_date')
    end_date_str = form_data.get('end_date')
    news_source_priority = form_data.get('news_source_priority', 'local_db_then_newsapi')
    trigger_scrape = form_data.get('trigger_scrape', False)
    scrape_domains_raw = form_data.get('scrape_domains', [])
    scrape_domains = [d.strip().lower() for d in scrape_domains_raw if isinstance(d, str) and d.strip()] if isinstance(scrape_domains_raw, list) else []
    custom_prompt = form_data.get('custom_prompt_llm', '')

    if not target_name: user_facing_errors.append("Target name/ticker is required.")
    if not start_date_str or not end_date_str: user_facing_errors.append("Start and End dates are required.")
    if not current_api_keys.get('gemini_is_valid'):
        user_facing_errors.append("Gemini API key is not configured or is placeholder.")
    if ('newsapi' in news_source_priority or news_source_priority == 'newsapi_only') and \
       (not current_api_keys.get('newsapi_is_valid')):
        user_facing_errors.append("NewsAPI key is not valid but selected as a source.")
    try:
        max_articles_llm = int(form_data.get('max_articles_llm', 5))
        if max_articles_llm < 1: max_articles_llm = 1
    except ValueError:
        user_facing_errors.append("Invalid value for Max articles for LLM."); max_articles_llm = 5

    if user_facing_errors:
        logger.warning(f"Ad-hoc request validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages}), 400

    query_start_date_obj = robust_date_parse(start_date_str)
    query_end_date_obj = robust_date_parse(end_date_str)
    actual_today_server = datetime.now(timezone.utc).date()

    if not query_start_date_obj or not query_end_date_obj:
        user_facing_errors.append("Invalid Start or End date format.")
    elif query_start_date_obj > query_end_date_obj:
        user_facing_errors.append("Start date cannot be after end date.")
    if user_facing_errors:
        logger.warning(f"Ad-hoc date validation failed: {user_facing_errors}")
        return jsonify({'error': True, 'messages': user_facing_errors, 'logs': ui_log_messages}), 400

    query_end_date_obj = min(query_end_date_obj, actual_today_server)

    llm_context_range_str = f"{query_start_date_obj.strftime('%Y-%m-%d')} to {query_end_date_obj.strftime('%Y-%m-%d')}"
    append_log_local(f"Ad-hoc analysis for '{target_name}' ({target_type}). Dates: {llm_context_range_str}", "INFO")

    if trigger_scrape:
        # On-demand scraping is currently unavailable — on_demand_fetcher.py was removed.
        # Kept as a graceful no-op (rather than deleting the whole trigger_scrape code path)
        # so the frontend doesn't break if it still sends trigger_scrape=true.
        # Local DB + NewsAPI fetching below are unaffected and still work normally.
        append_log_local(
            f"On-demand scraping requested for '{target_name}' but is currently unavailable "
            f"(on_demand_fetcher.py removed). Skipping scrape, continuing with Local DB / NewsAPI only.",
            "WARNING"
        )

    articles_for_analysis = []

    if news_source_priority in ['local_db_then_newsapi', 'local_db_only']:
        append_log_local(f"Fetching from Local DB for '{target_name}'", "INFO")
        db_keywords = [target_name]
        if target_type == "sector":
            cfg = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(target_name, {})
            db_keywords.extend(cfg.get("newsapi_keywords", [])[:2])
        elif target_type == "stock":
            for sec_data in gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.values():
                if target_name in sec_data.get("stocks", {}):
                    db_keywords.extend(sec_data["stocks"][target_name][:2]); break

        db_articles = db_crud.get_articles_for_analysis(db, query_start_date_obj, query_end_date_obj, list(set(db_keywords)), limit=max_articles_llm * 2)
        articles_for_analysis.extend(process_articles_for_llm(db_articles, target_name, db, source_type="db"))
        append_log_local(f"Found {len(articles_for_analysis)} articles from DB.", "INFO")

    # NOTE (known budget leak, accepted for now): this ad-hoc route calls
    # newsapi_helpers directly and does NOT go through ingestion.py's budget
    # tracker in ingestion_state.json. Occasional manual ad-hoc queries can
    # therefore spend NewsAPI calls the tracker doesn't count. If this route
    # gets heavy use, replace the block below with ingestion.ensure_*_coverage.
    newsapi_err_msg = None
    if news_source_priority == 'newsapi_only' or \
       (news_source_priority == 'local_db_then_newsapi' and len(articles_for_analysis) < max_articles_llm):
        needed = max_articles_llm - len(articles_for_analysis) if news_source_priority == 'local_db_then_newsapi' else max_articles_llm
        if needed > 0 and current_api_keys['newsapi_is_valid']:
            append_log_local(f"Fetching from NewsAPI for '{target_name}' (need ~{needed} more).", "INFO")
            newsapi_client, client_err = newsapi_helpers.get_newsapi_org_client(current_api_keys['newsapi'], append_log_local)
            if newsapi_client:
                api_keywords = [target_name]
                # (Logic for getting more specific api_keywords for stock/sector as before)
                if target_type == "stock":
                    found_stock_keywords = False
                    for sector_data_val_n in gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.values():
                        if target_name in sector_data_val_n.get("stocks", {}):
                            api_keywords.extend(sector_data_val_n["stocks"][target_name][:3]); found_stock_keywords = True; break
                    if not found_stock_keywords: api_keywords.extend([f"{target_name} stock", f"{target_name} share price"])
                elif target_type == "sector":
                     cfg = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG.get(target_name, {})
                     api_keywords.extend(cfg.get("newsapi_keywords", [])[:3])

                newsapi_data, newsapi_err_msg = newsapi_helpers.fetch_newsapi_articles(
                    newsapi_client, target_name, list(set(api_keywords)), gemini_utils.NEWSAPI_INDIA_MARKET_KEYWORDS,
                    query_start_date_obj, query_end_date_obj, max_articles_to_fetch=needed, append_log_func=append_log_local
                )
                existing_uris = {art['uri'] for art in articles_for_analysis}
                for napi_art in newsapi_data:
                    if napi_art['uri'] not in existing_uris: articles_for_analysis.append(napi_art) # Already processed by newsapi_helpers
                append_log_local(f"Total articles after NewsAPI: {len(articles_for_analysis)}.", "INFO")
            elif client_err: newsapi_err_msg = client_err; append_log_local(newsapi_err_msg, "ERROR")
        elif needed > 0: append_log_local("Skipping NewsAPI (key not valid or no articles needed).", "WARNING")

    articles_for_analysis.sort(key=lambda x: x.get('date', '1970-01-01'), reverse=True)
    articles_trimmed_for_llm = articles_for_analysis[:max_articles_llm]
    llm_analysis_result, current_target_error = None, newsapi_err_msg

    if not articles_trimmed_for_llm:
        msg = f"No relevant articles found for '{target_name}' from any source for LLM."
        append_log_local(msg, "WARNING"); current_target_error = (current_target_error + "; " + msg) if current_target_error else msg
    elif not current_api_keys['gemini_is_valid']:
        msg = f"Gemini API key not valid. LLM analysis skipped for '{target_name}'."; append_log_local(msg, "ERROR"); current_target_error = (current_target_error + "; " + msg) if current_target_error else msg
    else:
        append_log_local(f"Sending {len(articles_trimmed_for_llm)} articles to Gemini for '{target_name}'.", "INFO")
        llm_analysis_result, gemini_err = gemini_utils.analyze_news_with_gemini(
            current_api_keys['gemini'], [art['content'] for art in articles_trimmed_for_llm],
            target_name, llm_context_range_str, custom_prompt, append_log_local, target_type=target_type
        )
        if gemini_err: current_target_error = (current_target_error + "; " + gemini_err) if current_target_error else gemini_err

    daily_sentiment_data = []
    if articles_for_analysis:
        df = pd.DataFrame([a for a in articles_for_analysis if a.get('vader_score') is not None and a.get('date') != 'N/A'])
        if not df.empty and 'date' in df.columns and 'vader_score' in df.columns:
            df['date_obj'] = pd.to_datetime(df['date'], errors='coerce')
            df = df.dropna(subset=['date_obj', 'vader_score'])
            if not df.empty:
                daily_avg = df.groupby(df['date_obj'].dt.date)['vader_score'].mean().reset_index()
                daily_avg.rename(columns={'vader_score': 'avg_sentiment_score', 'date_obj': 'date'}, inplace=True)
                daily_avg['date'] = daily_avg['date'].astype(str)
                daily_sentiment_data = daily_avg.to_dict('records')
    append_log_local(f"Prepared {len(daily_sentiment_data)} daily sentiment points for chart.", "DEBUG")

    price_data = get_yfinance_prices(target_name, query_start_date_obj.strftime('%Y-%m-%d'), query_end_date_obj.strftime('%Y-%m-%d'), append_log_local) if target_type == "stock" else []

    return jsonify({
        'error': bool(current_target_error), 'messages': [current_target_error] if current_target_error else [f"Ad-hoc analysis complete."],
        'target_name': target_name, 'target_type': target_type, 'llm_analysis': llm_analysis_result,
        'articles_analyzed': articles_trimmed_for_llm, 'all_articles_fetched_count': len(articles_for_analysis),
        'daily_sentiment_data': daily_sentiment_data, 'price_data': price_data, 'logs': ui_log_messages
    })

def get_yfinance_prices(ticker, start_date_str, end_date_str, append_log_local):
    if not ticker: append_log_local("No ticker for yfinance.", "ERROR"); return []
    ticker_yf = ticker.upper()
    if '.' not in ticker_yf: ticker_yf = f"{ticker_yf}.NS"
    append_log_local(f"Fetching yfinance data for {ticker_yf} from {start_date_str} to {end_date_str}", "INFO")
    try:
        yf_end_dt = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)
        yf_end_str_incl = yf_end_dt.strftime("%Y-%m-%d")
        df = yf.download(ticker_yf, start=start_date_str, end=yf_end_str_incl, progress=False, auto_adjust=True)
        if df.empty:
            append_log_local(f"No price data for {ticker_yf} (attempt 1).", "WARNING")
            if ticker_yf.endswith(".NS"):
                ticker_plain = ticker_yf[:-3]
                append_log_local(f"Retrying yfinance for {ticker_plain}.", "INFO")
                df = yf.download(ticker_plain, start=start_date_str, end=yf_end_str_incl, progress=False, auto_adjust=True)
                if df.empty: append_log_local(f"Still no price data for {ticker_plain} (attempt 2).", "WARNING"); return []
            else: return []

        df_reset = df.reset_index()
        price_list = []
        for _, row in df_reset.iterrows():
            date_val, close_val = row.get('Date'), row.get('Close')
            if pd.isna(date_val) or pd.isna(close_val): continue

            fmt_date = ""
            if isinstance(date_val, (pd.Timestamp, datetime)): fmt_date = date_val.strftime('%Y-%m-%d')
            else:
                try: fmt_date = pd.to_datetime(str(date_val)).strftime('%Y-%m-%d')
                except: append_log_local(f"Could not format date: {date_val}. Skipping.", "ERROR"); continue

            try: num_close = float(close_val)
            except: append_log_local(f"Could not convert price '{close_val}' to float. Skipping.", "ERROR"); continue

            price_list.append({"date": fmt_date, "close_price": num_close})
        append_log_local(f"Processed {len(price_list)} price points for {ticker_yf}.", "INFO")
        return price_list
    except Exception as e:
        append_log_local(f"General error yfinance for {ticker_yf}: {e}", "ERROR")
        logger.error(f"Full yfinance error {ticker_yf}:", exc_info=True)
        return []

if __name__ == '__main__':
    logger.info(f"Nifty News Sentiment Analyzer starting...")
    try:
        create_db_and_tables()
        logger.info("Database tables checked/created successfully.")
    except Exception as e_db_create:
        logger.error(f"CRITICAL: Failed to create/check database tables on startup: {e_db_create}")

    # Trigger the background daily ingestion (RSS + Google News drip; NewsAPI is
    # reserved for on-demand top-ups) on startup -- but ONLY from the actual
    # worker process, not Werkzeug's reloader-monitor process. debug=True +
    # use_reloader=True means this whole __main__ block re-executes on every
    # code reload during development; without this WERKZEUG_RUN_MAIN check,
    # ingestion would restart redundantly on every single file save while
    # developing. maybe_run_daily_on_startup() is also itself safe to call
    # repeatedly -- it no-ops if today's cycle already finished.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        try:
            import ingestion
            ingestion.maybe_run_daily_on_startup()
        except Exception as e_ingestion:
            logger.error(f"Could not start background ingestion on startup: {e_ingestion}")

    port = int(os.environ.get("PORT", 5003))
    logger.info(f"Flask app running on http://0.0.0.0:{port}")
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=True)