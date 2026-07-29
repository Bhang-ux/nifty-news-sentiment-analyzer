# backfill_ingestion.py
"""
Coverage-aware backfill. Two entry points:
 
1. run_coverage_backfill()
     Called once per daily cycle (after RSS). Finds stocks with fewer than
     MIN_ARTICLES_PER_STOCK articles, sorts them worst-covered-first, and
     spends the remaining NewsAPI daily budget on exactly those stocks.
     Full article text is extracted via trafilatura from the real URLs
     (NewsAPI's own 'content' field is truncated to ~200 chars -- we don't
     save that; we fetch the page).
     Converges: after ~2-3 daily runs every stock that HAS news in the last
     ~28 days (NewsAPI free tier's search window) reaches the minimum, and
     from then on each run only tops up stragglers.
 
2. ensure_sector_coverage(sector_name, days=7, min_articles=10)
     Called from a Flask route when someone requests a sector and the DB
     doesn't have enough recent articles for it. Spends a small, capped
     slice of budget on that sector's least-covered stocks, right now.
     Run it in a background thread from Flask (example at bottom) so the
     request itself still returns instantly from the DB.
 
Shares the NewsAPI budget tracking in ingestion_state.json with
daily_ingestion.py, so the 90/day cap is respected across everything.
 
MUST live in the project root (same directory as daily_ingestion.py).
"""
 
import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
 
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
 
import trafilatura
from sqlalchemy import func
 
import config
from utils.database_models import SessionLocal, create_db_and_tables, ScrapedArticle, ArticleSector
from utils import newsapi_helpers, gemini_utils, sentiment_analyzer
from daily_ingestion import (
    load_state, save_state, get_remaining_budget, record_newsapi_call,
    build_unique_targets, save_article_if_new,
)
 
logger = logging.getLogger("backfill_ingestion")
 
MIN_ARTICLES_PER_STOCK = 5
NEWSAPI_LOOKBACK_DAYS = 28          # free tier can't search further back
ARTICLES_PER_BACKFILL_QUERY = 8
ON_DEMAND_BUDGET_CAP = 10           # max NewsAPI calls one Flask trigger may spend
FULLTEXT_MIN_CHARS = 300            # below this, keep NewsAPI's own snippet instead
 
 
# ---------------------------------------------------------------------------
# Coverage measurement
# ---------------------------------------------------------------------------
 
def get_stock_article_counts(db) -> dict:
    """{stock_name: article_count} for every configured stock, including 0s."""
    counts = dict(
        db.query(ScrapedArticle.related_stock, func.count(ScrapedArticle.id))
          .filter(ScrapedArticle.related_stock.isnot(None))
          .group_by(ScrapedArticle.related_stock).all()
    )
    _, stocks = build_unique_targets()
    return {name: counts.get(name, 0) for name in stocks}
 
 
def stocks_below_minimum(db, minimum=MIN_ARTICLES_PER_STOCK) -> list:
    """[(stock_name, count)] sorted worst-covered first."""
    counts = get_stock_article_counts(db)
    lacking = [(name, c) for name, c in counts.items() if c < minimum]
    lacking.sort(key=lambda x: x[1])
    return lacking
 
 
# ---------------------------------------------------------------------------
# Fetch one stock via NewsAPI, with full-text extraction
# ---------------------------------------------------------------------------
 
def _fetch_and_save_for_stock(db, state, stock_name, stock_info) -> int:
    """One NewsAPI call for one stock; returns number of new articles saved.
    Caller must have checked budget; this records the call."""
    newsapi_client, err = newsapi_helpers.get_newsapi_org_client(
        config.NEWSAPI_ORG_API_KEY, append_log_func=lambda m, l='info': None)
    if not newsapi_client:
        logger.error(f"NewsAPI client unavailable: {err}")
        return 0
 
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=NEWSAPI_LOOKBACK_DAYS)
    keywords = (stock_info.get("keywords") or [stock_name])[:5]
 
    record_newsapi_call(state)
    save_state(state)
 
    articles, err = newsapi_helpers.fetch_newsapi_articles(
        newsapi_client=newsapi_client,
        target_name_for_log=stock_name,
        query_keywords_list=keywords,
        context_keywords_list=gemini_utils.NEWSAPI_INDIA_MARKET_KEYWORDS,
        from_date_obj=from_date,
        to_date_obj=to_date,
        max_articles_to_fetch=ARTICLES_PER_BACKFILL_QUERY,
        append_log_func=lambda msg, lvl='info': logger.log(
            getattr(logging, lvl.upper(), logging.INFO), f"[{stock_name}] {msg}")
    )
    if err:
        logger.warning(f"NewsAPI error for '{stock_name}': {err}")
        return 0
 
    saved = 0
    for art in articles:
        url = art.get('uri')
        if not url:
            continue
        if db.query(ScrapedArticle).filter_by(url=url).first():
            continue
 
        # Upgrade: full text from the real page, not NewsAPI's ~200-char stub
        full_text = ""
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                full_text = (trafilatura.extract(
                    downloaded, include_comments=False,
                    include_tables=False, favor_recall=True) or "").strip()
        except Exception as e:
            logger.debug(f"Full-text fetch failed for {url}: {e}")
        article_text = full_text if len(full_text) >= FULLTEXT_MIN_CHARS \
            else (art.get('content') or "")
        if not article_text:
            continue
        time.sleep(1.0)   # polite delay for the page fetch
 
        pub_date = None
        if art.get('date') and art['date'] != 'N/A':
            try:
                pub_date = datetime.strptime(art['date'][:10], "%Y-%m-%d")
            except ValueError:
                pass
 
        headline = art.get('title', '')
        vader = sentiment_analyzer.get_vader_sentiment_score(
            f"{headline} {article_text[:3000]}")
 
        if save_article_if_new(
            db, url=url, headline=headline, article_text=article_text,
            pub_date=pub_date,
            source_domain=art.get('source', '') or urlparse(url).netloc,
            vader_score=vader,
            related_stock=stock_name,
            sector_names=stock_info.get("sectors", []),
            source='newsapi',
        ):
            saved += 1
    logger.info(f"Backfill '{stock_name}': {saved} new articles "
                f"({len(articles)} candidates)")
    return saved
 
 
# ---------------------------------------------------------------------------
# Entry point 1: daily coverage backfill
# ---------------------------------------------------------------------------
 
def run_coverage_backfill(minimum=MIN_ARTICLES_PER_STOCK,
                          budget_reserve=0) -> dict:
    """
    Spends remaining NewsAPI budget (minus budget_reserve) on the
    least-covered stocks. Returns stats.
    """
    create_db_and_tables()
    db = SessionLocal()
    state = load_state()
    stats = {"targets_attempted": 0, "articles_saved": 0, "budget_left": 0,
             "stocks_still_below_min": 0}
    try:
        _, all_stocks = build_unique_targets()
        lacking = stocks_below_minimum(db, minimum)
        logger.info(f"Coverage backfill: {len(lacking)} stocks below "
                    f"{minimum} articles; NewsAPI budget left: "
                    f"{get_remaining_budget(state)}")
 
        for stock_name, count in lacking:
            if get_remaining_budget(state) <= budget_reserve:
                logger.info("Backfill stopping: budget reserve reached.")
                break
            info = all_stocks.get(stock_name, {})
            stats["articles_saved"] += _fetch_and_save_for_stock(
                db, state, stock_name, info)
            stats["targets_attempted"] += 1
 
        stats["budget_left"] = get_remaining_budget(state)
        stats["stocks_still_below_min"] = len(stocks_below_minimum(db, minimum))
        logger.info(f"Coverage backfill done: {stats}")
        return stats
    finally:
        save_state(state)
        db.close()
 
 
# ---------------------------------------------------------------------------
# Entry point 2: on-demand, from Flask
# ---------------------------------------------------------------------------
 
def ensure_sector_coverage(sector_name, days=7, min_articles=10,
                           budget_cap=ON_DEMAND_BUDGET_CAP) -> dict:
    """
    If the DB has fewer than min_articles for this sector in the last `days`,
    immediately fetch for this sector's least-covered stocks, spending at
    most budget_cap NewsAPI calls. Safe to call on every sector request --
    returns instantly when coverage is already fine.
    """
    create_db_and_tables()
    db = SessionLocal()
    state = load_state()
    result = {"sector": sector_name, "had": 0, "fetched_targets": 0,
              "articles_saved": 0, "skipped": False}
    try:
        since = datetime.utcnow() - timedelta(days=days)
        have = (db.query(func.count(ScrapedArticle.id))
                  .join(ArticleSector,
                        ArticleSector.article_id == ScrapedArticle.id)
                  .filter(ArticleSector.sector_name == sector_name,
                          ScrapedArticle.publication_date >= since)
                  .scalar()) or 0
        result["had"] = have
        if have >= min_articles:
            result["skipped"] = True
            return result
 
        _, all_stocks = build_unique_targets()
        sector_stocks = {name: info for name, info in all_stocks.items()
                         if sector_name in info.get("sectors", [])}
        if not sector_stocks:
            logger.warning(f"ensure_sector_coverage: no stocks configured "
                           f"for sector '{sector_name}'")
            return result
 
        counts = get_stock_article_counts(db)
        ordered = sorted(sector_stocks.items(),
                         key=lambda kv: counts.get(kv[0], 0))
 
        spent = 0
        for stock_name, info in ordered:
            if spent >= budget_cap or get_remaining_budget(state) <= 0:
                break
            result["articles_saved"] += _fetch_and_save_for_stock(
                db, state, stock_name, info)
            result["fetched_targets"] += 1
            spent += 1
 
        logger.info(f"ensure_sector_coverage('{sector_name}'): {result}")
        return result
    finally:
        save_state(state)
        db.close()
 
 
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
    run_coverage_backfill()
 
 
# ---------------------------------------------------------------------------
# Flask integration example (paste the route logic into app.py):
#
#   import threading
#   from backfill_ingestion import ensure_sector_coverage
#
#   @app.route('/api/sector/<sector_name>')
#   def sector_articles(sector_name):
#       db = SessionLocal()
#       arts = db_crud.get_articles_by_sector(db, sector_name, limit=50)
#       db.close()
#       # if thin, top up in the background -- response still returns NOW
#       if len(arts) < 10:
#           threading.Thread(target=ensure_sector_coverage,
#                            args=(sector_name,), daemon=True).start()
#       return jsonify([{ "headline": a.headline,
#                         "date": str(a.publication_date),
#                         "stock": a.related_stock,
#                         "source": a.source } for a in arts])
# ---------------------------------------------------------------------------
