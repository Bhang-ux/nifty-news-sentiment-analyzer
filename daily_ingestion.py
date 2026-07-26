# daily_ingestion.py
"""
Ingestion logic for filling the DB across every stock and sector. Two ways to run it:
 
  1. Standalone / Task Scheduler:  python daily_ingestion.py
  2. Automatically from Flask on startup: app.py calls maybe_run_ingestion_on_startup(),
     which runs this in a background thread if today's cycle hasn't completed yet --
     Flask starts serving immediately, ingestion happens alongside it, not blocking it.
 
Fills the database across every unique target (22 sectors + unique stocks,
deduplicated across sector overlaps -- a stock like HDFC Bank that sits in
3 sectors is only fetched once, not 3 times, but gets tagged with ALL 3 sectors
via the ArticleSector table) using a priority queue keyed on "who hasn't been
fetched in the longest time."
 
Two sources, primary + fallback per target, and this genuinely means "try one,
fall back to the other" -- NewsAPI running out of daily budget partway through
no longer kills the rest of the run, it just switches remaining targets to
GNews-only:
  1. NewsAPI.org (primary)  -- reliable, structured, hard 100/day budget we track ourselves
  2. GNews (fallback) -- uses GNews's own get_full_article() (trafilatura-based),
     NOT utils/newsfetch_lib -- GNews returns news.google.com redirect links, and
     trafilatura's fetch_url() follows redirects as standard behavior, landing on
     the real article. get_full_article()'s return type isn't consistent across
     gnews versions/environments -- sometimes a dict, sometimes a newspaper Article
     object -- so the extraction handles both rather than assuming one.
 
Every saved article is tagged with: which stock/sector(s), which source
(newsapi/gnews), and publication time -- see utils/db_crud.py's
get_articles_by_stock / get_articles_by_sector / get_articles_by_source for
querying any of these dimensions, in any combination.
 
Prerequisite for the GNews fallback: pip install gnews trafilatura
If those aren't installed, this still runs fine on NewsAPI alone -- GNews
fallback just logs a warning and is skipped for that target.
"""
 
import sys
import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
 
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
 
import config
from utils.database_models import SessionLocal, create_db_and_tables, ScrapedArticle
from utils import gemini_utils, newsapi_helpers, sentiment_analyzer, db_crud
 
try:
    from gnews import GNews
    import trafilatura  # required by GNews.get_full_article()
    GNEWS_FALLBACK_AVAILABLE = True
except ImportError as e:
    GNEWS_FALLBACK_AVAILABLE = False
    _gnews_import_error = str(e)
 
# ─── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(PROJECT_ROOT, "daily_ingestion.log"))
    ]
)
logger = logging.getLogger("daily_ingestion")
 
# ─── Config ───────────────────────────────────────────────────────────────
STATE_FILE = os.path.join(PROJECT_ROOT, "ingestion_state.json")
DAILY_NEWSAPI_BUDGET = 90
ARTICLES_PER_SECTOR_QUERY = 15
ARTICLES_PER_STOCK_QUERY = 8
LOOKBACK_DAYS = 3
GNEWS_MAX_URLS_PER_FALLBACK = 5
 
 
# ─── State ────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not read state file, starting fresh: {e}")
    return {"last_fetched": {}, "daily_counter": {"date": "", "count": 0}, "last_full_cycle_date": ""}
 
 
def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
 
 
def get_remaining_budget(state):
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state["daily_counter"]["date"] != today_str:
        state["daily_counter"] = {"date": today_str, "count": 0}
    return DAILY_NEWSAPI_BUDGET - state["daily_counter"]["count"]
 
 
def record_newsapi_call(state):
    state["daily_counter"]["count"] += 1
 
 
def mark_fetched(state, target_name):
    state["last_fetched"][target_name] = datetime.now(timezone.utc).isoformat()
 
 
# ─── Build the deduplicated target list ─────────────────────────────────────
def build_unique_targets():
    """
    Returns:
      sectors: list of sector names (22)
      stocks: dict of {stock_name: {'sectors': [...ALL of them...], 'keywords': [...]}}
    """
    cfg = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG
    sectors = list(cfg.keys())
    stocks = {}
    for sector_name, sector_data in cfg.items():
        for stock_name, keywords in sector_data.get("stocks", {}).items():
            if stock_name not in stocks:
                stocks[stock_name] = {"sectors": [], "keywords": keywords}
            stocks[stock_name]["sectors"].append(sector_name)
    return sectors, stocks
 
 
# ─── Storage: shared by both sources ────────────────────────────────────────
def save_article_if_new(db, url, headline, article_text, pub_date, source_domain,
                         vader_score, related_stock, sector_names, source):
    """
    sector_names: the FULL list of sectors this article is relevant to (not just one) --
    gets recorded in the ArticleSector join table via tag_article_sectors(), so a
    multi-sector stock is correctly discoverable under every sector it belongs to.
    related_sector (the single-value column) still gets set too, to the first sector,
    purely for backward compatibility with older code that reads that column directly.
    source: 'newsapi' or 'gnews' -- which fetch path actually found this article.
    """
    existing = db.query(ScrapedArticle).filter_by(url=url).first()
    if existing:
        return False
    entry = ScrapedArticle(
        url=url,
        headline=headline or "",
        article_text=article_text or "",
        publication_date=pub_date,
        download_date=datetime.now(timezone.utc).replace(tzinfo=None),
        source_domain=source_domain or "",
        vader_score=vader_score,
        related_sector=(sector_names[0] if sector_names else None),
        related_stock=related_stock,
        source=source,
    )
    db.add(entry)
    try:
        db.commit()
        db.refresh(entry)  # need entry.id populated for the sector-tagging below
    except Exception as e:
        logger.error(f"DB commit failed for {url}: {e}")
        db.rollback()
        return False
 
    if sector_names:
        db_crud.tag_article_sectors(db, entry.id, sector_names)
    return True
 
 
# ─── Source 1: NewsAPI (primary) ────────────────────────────────────────────
def fetch_via_newsapi(newsapi_client, db, target_name, keywords, is_sector, sector_names, related_stock):
    """Returns (saved_any: bool, error: str|None)."""
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=LOOKBACK_DAYS)
    max_articles = ARTICLES_PER_SECTOR_QUERY if is_sector else ARTICLES_PER_STOCK_QUERY
 
    articles, err = newsapi_helpers.fetch_newsapi_articles(
        newsapi_client=newsapi_client,
        target_name_for_log=target_name,
        query_keywords_list=keywords[:5],
        context_keywords_list=gemini_utils.NEWSAPI_INDIA_MARKET_KEYWORDS,
        from_date_obj=from_date,
        to_date_obj=to_date,
        max_articles_to_fetch=max_articles,
        append_log_func=lambda msg, lvl='info': logger.log(getattr(logging, lvl.upper(), logging.INFO), f"[{target_name}] {msg}")
    )
    if err:
        logger.warning(f"NewsAPI error for '{target_name}': {err}")
        return False, err
 
    saved_count = 0
    for art in articles:
        pub_date = None
        if art.get('date') and art['date'] != 'N/A':
            try:
                pub_date = datetime.strptime(art['date'][:10], "%Y-%m-%d")
            except ValueError:
                pass
        was_new = save_article_if_new(
            db, url=art['uri'], headline=art.get('title', ''), article_text=art['content'],
            pub_date=pub_date, source_domain=art.get('source', ''),
            vader_score=art.get('vader_score'),
            related_stock=related_stock, sector_names=sector_names, source='newsapi'
        )
        if was_new:
            saved_count += 1
 
    logger.info(f"NewsAPI: '{target_name}' -> {saved_count} new articles saved ({len(articles)} fetched)")
    return saved_count > 0, None
 
 
# ─── Source 2: GNews fallback (uses gnews's own get_full_article, NOT newsfetch_lib) ──
def fetch_via_gnews_fallback(db, target_name, sector_names, related_stock):
    """Returns True if at least one new article was saved. No-ops safely if unavailable."""
    if not GNEWS_FALLBACK_AVAILABLE:
        logger.warning(f"GNews fallback unavailable for '{target_name}': {_gnews_import_error}")
        return False
 
    try:
        gnews_client = GNews(language='en', country='IN', max_results=GNEWS_MAX_URLS_PER_FALLBACK,
                              period=f'{LOOKBACK_DAYS}d')
        results = gnews_client.get_news(target_name)
    except Exception as e:
        logger.error(f"GNews search failed for '{target_name}': {e}")
        return False
 
    if not results:
        logger.info(f"GNews: no results for '{target_name}'")
        return False
 
    saved_count = 0
    for item in results[:GNEWS_MAX_URLS_PER_FALLBACK]:
        url = item.get('url')
        headline = item.get('title')
        if not url or not headline:
            continue
        existing = db.query(ScrapedArticle).filter_by(url=url).first()
        if existing:
            continue
 
        try:
            full = gnews_client.get_full_article(url)
        except Exception as e:
            logger.warning(f"GNews fallback: full-article extraction failed for {url}: {e}")
            continue
 
        # get_full_article()'s return type isn't consistent across gnews versions/environments --
        # sometimes a plain {"text":..., "url":...} dict, sometimes a newspaper Article object
        # (which has .text as an attribute, not a dict key). Handle both rather than assume one.
        article_text = None
        if isinstance(full, dict):
            article_text = full.get('text')
        elif hasattr(full, 'text'):
            article_text = full.text
        else:
            logger.warning(f"GNews fallback: unrecognized return type from get_full_article for {url}: {type(full)}")
            continue
 
        if not article_text:
            continue
 
        pub_date = None
        raw_date = item.get('published date')
        if raw_date:
            try:
                from email.utils import parsedate_to_datetime
                pub_date = parsedate_to_datetime(raw_date).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass
 
        publisher = item.get('publisher') or {}
        source_name = publisher.get('title', '') if isinstance(publisher, dict) else str(publisher)
 
        vader_score = sentiment_analyzer.get_vader_sentiment_score(f"{headline} {article_text}")
        was_new = save_article_if_new(
            db, url=url, headline=headline, article_text=article_text,
            pub_date=pub_date, source_domain=source_name,
            vader_score=vader_score,
            related_stock=related_stock, sector_names=sector_names, source='gnews'
        )
        if was_new:
            saved_count += 1
        time.sleep(1.0)
 
    logger.info(f"GNews fallback: '{target_name}' -> {saved_count} new articles saved")
    return saved_count > 0
 
 
# ─── Main ingestion cycle -- the reusable core, callable from anywhere ─────
def run_ingestion_cycle():
    logger.info("=" * 60)
    logger.info("Ingestion cycle starting")
    create_db_and_tables()
    db = SessionLocal()
    state = load_state()
 
    newsapi_client, client_err = newsapi_helpers.get_newsapi_org_client(
        config.NEWSAPI_ORG_API_KEY, append_log_func=lambda m, l='info': logger.info(m)
    )
    if not newsapi_client:
        logger.error(f"Cannot start: NewsAPI client unavailable ({client_err}). Check your .env NEWSAPI_ORG_API_KEY.")
        db.close()
        return
 
    sectors, stocks = build_unique_targets()
    logger.info(f"Targets: {len(sectors)} sectors + {len(stocks)} unique stocks = {len(sectors) + len(stocks)} total")
 
    all_targets = (
        [(name, True, gemini_utils.NIFTY_SECTORS_QUERY_CONFIG[name].get("newsapi_keywords", [name]), [name], name)
         for name in sectors] +
        [(name, False, info["keywords"] or [name], info["sectors"], name)
         for name, info in stocks.items()]
    )
    all_targets.sort(key=lambda t: state["last_fetched"].get(t[0], ""))
 
    processed = 0
    newsapi_exhausted_at = None
    for target_name, is_sector, keywords, sector_names, related_stock in all_targets:
        remaining = get_remaining_budget(state)
        got_articles = False
 
        if remaining > 0:
            record_newsapi_call(state)
            got_articles, err = fetch_via_newsapi(
                newsapi_client, db, target_name, keywords, is_sector,
                sector_names=sector_names,
                related_stock=(None if is_sector else related_stock),
            )
        else:
            if newsapi_exhausted_at is None:
                newsapi_exhausted_at = processed
                logger.info(f"NewsAPI budget exhausted after {processed} targets -- "
                            f"switching remaining {len(all_targets) - processed} targets to GNews-only.")
 
        if not got_articles:
            fetch_via_gnews_fallback(
                db, target_name,
                sector_names=sector_names,
                related_stock=(None if is_sector else related_stock),
            )
 
        mark_fetched(state, target_name)
        processed += 1
        save_state(state)
 
    if processed == len(all_targets):
        state["last_full_cycle_date"] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        save_state(state)
 
    stats = db_crud.get_inventory_stats(db)
    db.close()
    budget_note = f" (NewsAPI exhausted after {newsapi_exhausted_at} targets, rest ran GNews-only)" \
        if newsapi_exhausted_at is not None else ""
    logger.info(f"Cycle complete. Processed {processed}/{len(all_targets)} targets{budget_note}.")
    logger.info(f"Inventory now: {stats['total_articles']} total articles | by source: {stats['by_source']} | "
                f"{stats['unique_stocks_covered']} stocks covered | {stats['unique_sectors_covered']} sectors covered")
    logger.info("=" * 60)
 
 
# ─── Entry point 2: called from app.py on Flask startup ────────────────────
def maybe_run_ingestion_on_startup():
    """
    Non-blocking: starts run_ingestion_cycle() in a background thread if
    today's cycle hasn't already completed, then returns immediately so
    Flask can keep starting up. Safe to call every time app.py starts --
    won't re-trigger a redundant cycle if one already finished today.
    """
    state = load_state()
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state.get("last_full_cycle_date") == today_str:
        logger.info("Ingestion already completed today -- not starting another cycle.")
        return
    logger.info("Starting ingestion cycle in background thread (Flask startup trigger)...")
    thread = threading.Thread(target=run_ingestion_cycle, daemon=True, name="ingestion-cycle")
    thread.start()
 
 
if __name__ == '__main__':
    run_ingestion_cycle()