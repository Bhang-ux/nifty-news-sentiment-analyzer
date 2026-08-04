# ingestion.py
"""
THE ingestion module -- replaces daily_ingestion.py, rss_ingestion.py,
backfill_ingestion.py and gnews_search_backfill.py with one file.
 
Design (three tiers, each doing what it's good at):
 
  TIER A -- RSS (daily, free, unlimited):
      14 publisher feeds (ET, Moneycontrol, LiveMint, BusinessLine).
      Direct URLs -> trafilatura full text -> word-boundary matching against
      all 22 sectors + 252 stocks. Captures the fresh daily news flow.
 
  TIER B -- Google News search drip (daily, free, rate-limited):
      For every stock with fewer than MIN_RECENT_ARTICLES articles from the
      last FRESH_WINDOW_DAYS days, searches Google News per stock (keyless,
      unlimited discovery), decodes the encrypted links slowly with backoff,
      extracts full text. Keeps EVERY stock topped up with recent coverage,
      worst-covered first.
 
  TIER C -- NewsAPI (ON-DEMAND ONLY, never scheduled):
      The 90/day budget is reserved for ensure_stock_coverage() /
      ensure_sector_coverage(), called from Flask when a user requests a
      stock/sector and the DB lacks enough recent articles. Full text is
      fetched from the article URLs (NewsAPI's own content is truncated).
 
  All tiers save through ONE function (save_article_if_new): dedupe by URL,
  multi-sector tagging via ArticleSector, VADER at ingest, source column
  ('rss:<publisher>' / 'gnews-search' / 'newsapi').
 
  Retrieval for sentiment/RAG: get_recent(stock=..., sector=..., days=N)
  returns articles published after the cutoff, NEWEST FIRST. Articles with
  no parsed publication date fall back to download_date so they're never
  silently lost.
 
Concurrency note: safe to run from the terminal WHILE Flask is running.
The DB uses WAL mode + check_same_thread=False (set in database_models.py),
so one writer (this script) and many readers (Flask) coexist fine. Avoid
running TWO bulk fills at the same time, though -- they'd fight over
Google's rate limit and duplicate effort.
 
Entry points:
  python ingestion.py                     # daily run: RSS + drip (once/day guard)
  python ingestion.py --force             # daily run, ignore the once/day guard
  python ingestion.py --rss-only / --drip-only
  python ingestion.py --check-feeds
  python ingestion.py --ensure-sector "Nifty Bank"
  python ingestion.py --ensure-stock "Infosys"
 
  BULK FILL (e.g. overnight, works alongside running Flask):
  python ingestion.py --drip-only --minimum 50 --max-stocks 252 --loop 20
      -> repeat forever: push every stock toward 50 recent articles,
         rest 20 minutes between passes, Ctrl+C to stop (progress is
         saved continuously, stopping loses nothing)
 
  From Flask:  ingestion.maybe_run_daily_on_startup()   (background thread)
 
Dependencies: pip install feedparser trafilatura requests googlenewsdecoder
"""
 
from __future__ import annotations
 
import os
import sys
import re
import json
import time
import logging
import argparse
import threading
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse
 
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
 
import requests
import feedparser
import trafilatura
from sqlalchemy import func, or_, and_
 
import config
from utils.database_models import (SessionLocal, create_db_and_tables,
                                   ScrapedArticle, ArticleSector)
from utils import gemini_utils, newsapi_helpers, sentiment_analyzer, db_crud
 
try:
    from googlenewsdecoder import gnewsdecoder
    DECODER_AVAILABLE = True
except ImportError:
    DECODER_AVAILABLE = False
 
# ─── Logging ────────────────────────────────────────────────────────────────
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(PROJECT_ROOT, "ingestion.log"),
                                  encoding="utf-8")])
logger = logging.getLogger("ingestion")
 
# ─── Tunables ───────────────────────────────────────────────────────────────
STATE_FILE = os.path.join(PROJECT_ROOT, "ingestion_state.json")
DAILY_NEWSAPI_BUDGET = 90
 
FRESH_WINDOW_DAYS = 30        # "recent" = published within this many days
MIN_RECENT_ARTICLES = 5       # every stock should have at least this many recent
DRIP_MAX_STOCKS_PER_RUN = 40  # gap stocks worked per daily drip run
DECODE_DELAY = 3.0            # seconds between Google decode calls
MAX_DECODE_ATTEMPTS_PER_STOCK = 12
MAX_CONSECUTIVE_DECODE_FAILS = 8
 
ON_DEMAND_BUDGET_CAP = 10     # max NewsAPI calls per ensure_* trigger
ON_DEMAND_MIN_SECTOR = 10     # sector considered "thin" below this many recent
ON_DEMAND_DAYS = 7            # ...within this window
NEWSAPI_LOOKBACK_DAYS = 28    # free tier can't search further back
 
MIN_ARTICLE_CHARS = 400
REQUEST_TIMEOUT = 15
POLITE_DELAY = 1.0
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
 
FEEDS: dict[str, list[str]] = {
    "economictimes": [
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        "https://economictimes.indiatimes.com/industry/banking/finance/rssfeeds/13358259.cms",
        "https://economictimes.indiatimes.com/prime/rssfeeds/2147477890.cms",
    ],
    "moneycontrol": [
        "https://www.moneycontrol.com/rss/business.xml",
        "https://www.moneycontrol.com/rss/marketreports.xml",
        "https://www.moneycontrol.com/rss/results.xml",
        "https://www.moneycontrol.com/rss/economy.xml",
        "https://www.moneycontrol.com/rss/latestnews.xml",
    ],
    "livemint": [
        "https://www.livemint.com/rss/markets",
        "https://www.livemint.com/rss/companies",
        "https://www.livemint.com/rss/money",
    ],
    "businessline": [
        "https://www.thehindubusinessline.com/markets/feeder/default.rss",
        "https://www.thehindubusinessline.com/companies/feeder/default.rss",
    ],
}
 
 
# ═══════════════════════════════════════════════════════════════════════════
# State (same file/keys as before -- no migration needed)
# ═══════════════════════════════════════════════════════════════════════════
 
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"State file unreadable, starting fresh: {e}")
    return {"last_fetched": {}, "daily_counter": {"date": "", "count": 0},
            "last_full_cycle_date": ""}
 
 
def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
 
 
def get_remaining_budget(state: dict) -> int:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state["daily_counter"]["date"] != today:
        state["daily_counter"] = {"date": today, "count": 0}
    return DAILY_NEWSAPI_BUDGET - state["daily_counter"]["count"]
 
 
def record_newsapi_call(state: dict) -> None:
    state["daily_counter"]["count"] += 1
 
 
# ═══════════════════════════════════════════════════════════════════════════
# Targets and matching
# ═══════════════════════════════════════════════════════════════════════════
 
def build_unique_targets():
    """sectors: [name]; stocks: {name: {'sectors': [...], 'keywords': [...]}}"""
    cfg = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG
    sectors = list(cfg.keys())
    stocks: dict[str, dict] = {}
    for sector_name, sector_data in cfg.items():
        for stock_name, keywords in sector_data.get("stocks", {}).items():
            stocks.setdefault(stock_name, {"sectors": [], "keywords": keywords})
            stocks[stock_name]["sectors"].append(sector_name)
    return sectors, stocks
 
 
def build_alias_index():
    """[(compiled_pattern, canonical, is_sector, sectors_of_target)], longest
    aliases first. Word-boundary so 'TCS' can't match inside another word."""
    sectors, stocks = build_unique_targets()
    raw = []
    for name in sectors:
        kws = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG[name].get("newsapi_keywords", [])
        for alias in {name, *kws}:
            if len(alias.strip()) >= 3:
                raw.append((alias.strip(), name, True, [name]))
    for name, info in stocks.items():
        for alias in {name, *(info["keywords"] or [])}:
            if len(alias.strip()) >= 3:
                raw.append((alias.strip(), name, False, info["sectors"]))
    raw.sort(key=lambda r: len(r[0]), reverse=True)
    return [(re.compile(r"(?<!\w)" + re.escape(a) + r"(?!\w)", re.IGNORECASE),
             canon, is_sec, secs) for a, canon, is_sec, secs in raw]
 
 
def match_text(title: str, body: str, alias_index) -> tuple[str | None, list[str]]:
    """Returns (related_stock, all_sector_names) for a piece of text."""
    haystack = f"{title} {body[:1500]}"
    related_stock = None
    sector_names: list[str] = []
    seen = set()
    for pattern, canonical, is_sector, secs in alias_index:
        if canonical in seen or not pattern.search(haystack):
            continue
        seen.add(canonical)
        if is_sector:
            if canonical not in sector_names:
                sector_names.append(canonical)
        else:
            if related_stock is None:
                related_stock = canonical
            for s in secs:
                if s not in sector_names:
                    sector_names.append(s)
    return related_stock, sector_names
 
 
# ═══════════════════════════════════════════════════════════════════════════
# The ONE save path (unchanged semantics from daily_ingestion)
# ═══════════════════════════════════════════════════════════════════════════
 
def save_article_if_new(db, url, headline, article_text, pub_date, source_domain,
                        vader_score, related_stock, sector_names, source) -> bool:
    if db.query(ScrapedArticle).filter_by(url=url).first():
        return False
    entry = ScrapedArticle(
        url=url, headline=headline or "", article_text=article_text or "",
        publication_date=pub_date,
        download_date=datetime.now(timezone.utc).replace(tzinfo=None),
        source_domain=source_domain or "", vader_score=vader_score,
        related_sector=(sector_names[0] if sector_names else None),
        related_stock=related_stock, source=source)
    db.add(entry)
    try:
        db.commit()
        db.refresh(entry)
    except Exception as e:
        logger.error(f"DB commit failed for {url}: {e}")
        db.rollback()
        return False
    if sector_names:
        db_crud.tag_article_sectors(db, entry.id, sector_names)
    return True
 
 
def _extract(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        return (trafilatura.extract(downloaded, include_comments=False,
                                    include_tables=False,
                                    favor_recall=True) or "").strip()
    except Exception as e:
        logger.debug(f"Extraction error {url}: {e}")
        return ""
 
 
def _vader(headline: str, text: str) -> float:
    # Same window sentiment_analyzer.prepare_scoring_text() defines -- what
    # FinBERT sees too. Keeps every NEW article's VADER score comparable to
    # its FinBERT score from the moment it's ingested, not just historically
    # (rescale_vader.py fixed existing rows once; this stops the mismatch
    # from ever recurring for new ones).
    return sentiment_analyzer.get_vader_sentiment_score(
        sentiment_analyzer.prepare_scoring_text(headline, text))
 
 
def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
 
 
# ═══════════════════════════════════════════════════════════════════════════
# Coverage measurement (freshness-aware, NULL-date safe)
# ═══════════════════════════════════════════════════════════════════════════
 
def _effective_date():
    """publication_date, falling back to download_date when NULL."""
    return func.coalesce(ScrapedArticle.publication_date,
                         ScrapedArticle.download_date)
 
 
def stocks_below_recent_minimum(db, minimum=MIN_RECENT_ARTICLES,
                                days=FRESH_WINDOW_DAYS) -> list[tuple[str, int]]:
    """[(stock, recent_count)] for stocks under the freshness floor, worst first."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    counts = dict(
        db.query(ScrapedArticle.related_stock, func.count(ScrapedArticle.id))
          .filter(ScrapedArticle.related_stock.isnot(None),
                  _effective_date() >= cutoff)
          .group_by(ScrapedArticle.related_stock).all())
    _, stocks = build_unique_targets()
    lacking = [(name, counts.get(name, 0)) for name in stocks
               if counts.get(name, 0) < minimum]
    lacking.sort(key=lambda x: x[1])
    return lacking
 
 
def recent_sector_count(db, sector_name, days) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    return (db.query(func.count(ScrapedArticle.id))
              .join(ArticleSector, ArticleSector.article_id == ScrapedArticle.id)
              .filter(ArticleSector.sector_name == sector_name,
                      _effective_date() >= cutoff).scalar()) or 0
 
 
# ═══════════════════════════════════════════════════════════════════════════
# TIER A: RSS
# ═══════════════════════════════════════════════════════════════════════════
 
def _fetch_feed(url: str) -> list[dict]:
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        if parsed.bozo and not parsed.entries:
            logger.warning(f"Feed unparseable: {url}")
            return []
        return list(parsed.entries)
    except Exception as e:
        logger.warning(f"Feed fetch failed: {url} ({e})")
        return []
 
 
def run_rss(db, alias_index, limit: int | None = None) -> dict:
    stats = {"entries": 0, "saved": 0, "dup": 0, "empty": 0, "no_target": 0}
    seen: set[str] = set()
    extracted = 0
    for publisher, feed_urls in FEEDS.items():
        for feed_url in feed_urls:
            for entry in _fetch_feed(feed_url):
                stats["entries"] += 1
                url = (entry.get("link") or "").strip()
                title = (entry.get("title") or "").strip()
                if not url or not title or "news.google.com" in url:
                    continue
                if url in seen or db.query(ScrapedArticle).filter_by(url=url).first():
                    stats["dup"] += 1
                    continue
                seen.add(url)
                if limit is not None and extracted >= limit:
                    logger.info(f"RSS limit {limit} reached")
                    logger.info(f"RSS done: {stats}")
                    return stats
 
                text = _extract(url)
                extracted += 1
                time.sleep(POLITE_DELAY)
                if len(text) < MIN_ARTICLE_CHARS:
                    stats["empty"] += 1
                    continue
 
                related_stock, sector_names = match_text(title, text, alias_index)
                if related_stock is None and not sector_names:
                    stats["no_target"] += 1
                    continue
 
                pub = None
                raw = entry.get("published") or entry.get("updated")
                if raw:
                    try:
                        pub = _naive_utc(parsedate_to_datetime(raw))
                    except (ValueError, TypeError):
                        pass
 
                if save_article_if_new(
                        db, url=url, headline=title, article_text=text,
                        pub_date=pub, source_domain=urlparse(url).netloc,
                        vader_score=_vader(title, text),
                        related_stock=related_stock, sector_names=sector_names,
                        source=f"rss:{publisher}"):
                    stats["saved"] += 1
                    logger.info(f"RSS saved [{publisher}] '{title[:70]}'")
    logger.info(f"RSS done: {stats}")
    return stats
 
 
def check_feeds() -> None:
    for publisher, feed_urls in FEEDS.items():
        for url in feed_urls:
            entries = _fetch_feed(url)
            status = f"OK ({len(entries)})" if entries else "DEAD"
            print(f"[{status:>10}] {publisher:<15} {url}")
 
 
# ═══════════════════════════════════════════════════════════════════════════
# TIER B: Google News search drip (freshness maintainer)
# ═══════════════════════════════════════════════════════════════════════════
 
def _decode(redirect_url: str) -> str | None:
    try:
        result = gnewsdecoder(redirect_url, interval=1)
        if isinstance(result, dict) and result.get("status"):
            return result.get("decoded_url")
        return None
    except Exception:
        return None
 
 
def _drip_one_stock(db, stock_name, sectors_of_stock, need,
                    fail_streak: list) -> int:
    url = ("https://news.google.com/rss/search?q=" + quote(f'"{stock_name}"')
           + "&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        entries = list(feedparser.parse(resp.content).entries)
    except Exception as e:
        logger.warning(f"Drip search failed '{stock_name}': {e}")
        fail_streak[0] += 1          # search failures count too --
        return 0                     # 8 in a row = Google blocking, stop the pass
 
    saved = attempts = 0
    for entry in entries:
        if saved >= need or attempts >= MAX_DECODE_ATTEMPTS_PER_STOCK \
                or fail_streak[0] >= MAX_CONSECUTIVE_DECODE_FAILS:
            break
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
 
        attempts += 1
        real_url = _decode(link)
        time.sleep(DECODE_DELAY)
        if not real_url:
            fail_streak[0] += 1
            if fail_streak[0] in (3, 5):
                pause = 30 * fail_streak[0]
                logger.warning(f"{fail_streak[0]} decode failures -- "
                               f"backing off {pause}s")
                time.sleep(pause)
            continue
        fail_streak[0] = 0
 
        if db.query(ScrapedArticle).filter_by(url=real_url).first():
            continue
        text = _extract(real_url)
        if len(text) < MIN_ARTICLE_CHARS:
            continue
 
        pub = None
        raw = entry.get("published")
        if raw:
            try:
                pub = _naive_utc(parsedate_to_datetime(raw))
            except (ValueError, TypeError):
                pass
 
        if save_article_if_new(
                db, url=real_url, headline=title, article_text=text,
                pub_date=pub, source_domain=urlparse(real_url).netloc,
                vader_score=_vader(title, text),
                related_stock=stock_name, sector_names=sectors_of_stock,
                source='gnews-search'):
            saved += 1
            logger.info(f"Drip saved [{stock_name}] '{title[:70]}'")
    return saved
 
 
def run_drip(db, max_stocks=DRIP_MAX_STOCKS_PER_RUN,
             minimum=MIN_RECENT_ARTICLES, days=FRESH_WINDOW_DAYS) -> dict:
    stats = {"stocks": 0, "saved": 0, "stopped_early": False}
    if not DECODER_AVAILABLE:
        logger.warning("googlenewsdecoder not installed -- drip skipped "
                       "(pip install googlenewsdecoder)")
        return stats
    _, all_stocks = build_unique_targets()
    lacking = stocks_below_recent_minimum(db, minimum, days)
    logger.info(f"Drip: {len(lacking)} stocks below {minimum} recent "
                f"({days}d) articles; working {min(max_stocks, len(lacking))}")
    fail_streak = [0]
    for stock_name, count in lacking[:max_stocks]:
        if fail_streak[0] >= MAX_CONSECUTIVE_DECODE_FAILS:
            logger.warning("Google rate-limiting -- drip stopping for now")
            stats["stopped_early"] = True
            break
        info = all_stocks.get(stock_name, {})
        got = _drip_one_stock(db, stock_name, info.get("sectors", []),
                              minimum - count, fail_streak)
        stats["stocks"] += 1
        stats["saved"] += got
    logger.info(f"Drip done: {stats}")
    return stats
 
 
# ═══════════════════════════════════════════════════════════════════════════
# TIER C: NewsAPI -- ON-DEMAND ONLY
# ═══════════════════════════════════════════════════════════════════════════
 
def _newsapi_fetch_stock(db, state, stock_name, stock_info) -> int:
    """One budgeted NewsAPI call for one stock, full-text upgraded. Saves."""
    client, err = newsapi_helpers.get_newsapi_org_client(
        config.NEWSAPI_ORG_API_KEY, append_log_func=lambda m, l='info': None)
    if not client:
        logger.error(f"NewsAPI client unavailable: {err}")
        return 0
    record_newsapi_call(state)
    save_state(state)
 
    to_d = datetime.now(timezone.utc).date()
    from_d = to_d - timedelta(days=NEWSAPI_LOOKBACK_DAYS)
    articles, err = newsapi_helpers.fetch_newsapi_articles(
        newsapi_client=client, target_name_for_log=stock_name,
        query_keywords_list=(stock_info.get("keywords") or [stock_name])[:5],
        context_keywords_list=gemini_utils.NEWSAPI_INDIA_MARKET_KEYWORDS,
        from_date_obj=from_d, to_date_obj=to_d, max_articles_to_fetch=8,
        append_log_func=lambda msg, lvl='info': logger.log(
            getattr(logging, lvl.upper(), logging.INFO),
            f"[{stock_name}] {msg}"))
    if err:
        logger.warning(f"NewsAPI error '{stock_name}': {err}")
        return 0
 
    saved = 0
    for art in articles:
        url = art.get('uri')
        if not url or db.query(ScrapedArticle).filter_by(url=url).first():
            continue
        full = _extract(url)
        time.sleep(POLITE_DELAY)
        text = full if len(full) >= 300 else (art.get('content') or "")
        if not text:
            continue
        pub = None
        if art.get('date') and art['date'] != 'N/A':
            try:
                pub = datetime.strptime(art['date'][:10], "%Y-%m-%d")
            except ValueError:
                pass
        title = art.get('title', '')
        if save_article_if_new(
                db, url=url, headline=title, article_text=text, pub_date=pub,
                source_domain=art.get('source', '') or urlparse(url).netloc,
                vader_score=_vader(title, text), related_stock=stock_name,
                sector_names=stock_info.get("sectors", []), source='newsapi'):
            saved += 1
    logger.info(f"NewsAPI on-demand '{stock_name}': {saved} saved")
    return saved
 
 
def ensure_stock_coverage(stock_name, days=ON_DEMAND_DAYS,
                          min_articles=MIN_RECENT_ARTICLES) -> dict:
    """Call from Flask when a stock is requested. Instant no-op if coverage OK."""
    create_db_and_tables()
    db = SessionLocal()
    state = load_state()
    result = {"stock": stock_name, "had": 0, "saved": 0, "skipped": False}
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        have = (db.query(func.count(ScrapedArticle.id))
                  .filter(ScrapedArticle.related_stock == stock_name,
                          _effective_date() >= cutoff).scalar()) or 0
        result["had"] = have
        if have >= min_articles:
            result["skipped"] = True
            return result
        if get_remaining_budget(state) <= 0:
            logger.warning("ensure_stock_coverage: NewsAPI budget exhausted "
                           "(resets 00:00 UTC)")
            return result
        _, all_stocks = build_unique_targets()
        info = all_stocks.get(stock_name)
        if info is None:
            logger.warning(f"Unknown stock '{stock_name}'")
            return result
        result["saved"] = _newsapi_fetch_stock(db, state, stock_name, info)
        return result
    finally:
        save_state(state)
        db.close()
        logger.info(f"ensure_stock_coverage: {result}")
 
 
def ensure_sector_coverage(sector_name, days=ON_DEMAND_DAYS,
                           min_articles=ON_DEMAND_MIN_SECTOR,
                           budget_cap=ON_DEMAND_BUDGET_CAP) -> dict:
    """Call from Flask when a sector is requested. Instant no-op if coverage OK."""
    create_db_and_tables()
    db = SessionLocal()
    state = load_state()
    result = {"sector": sector_name, "had": 0, "targets": 0, "saved": 0,
              "skipped": False}
    try:
        have = recent_sector_count(db, sector_name, days)
        result["had"] = have
        if have >= min_articles:
            result["skipped"] = True
            return result
        _, all_stocks = build_unique_targets()
        sector_stocks = {n: i for n, i in all_stocks.items()
                         if sector_name in i.get("sectors", [])}
        if not sector_stocks:
            logger.warning(f"No stocks configured for sector '{sector_name}'")
            return result
        cutoff = datetime.utcnow() - timedelta(days=FRESH_WINDOW_DAYS)
        counts = dict(
            db.query(ScrapedArticle.related_stock, func.count(ScrapedArticle.id))
              .filter(ScrapedArticle.related_stock.in_(sector_stocks.keys()),
                      _effective_date() >= cutoff)
              .group_by(ScrapedArticle.related_stock).all())
        ordered = sorted(sector_stocks.items(),
                         key=lambda kv: counts.get(kv[0], 0))
        for stock_name, info in ordered:
            if result["targets"] >= budget_cap or get_remaining_budget(state) <= 0:
                break
            result["saved"] += _newsapi_fetch_stock(db, state, stock_name, info)
            result["targets"] += 1
        return result
    finally:
        save_state(state)
        db.close()
        logger.info(f"ensure_sector_coverage: {result}")
 
 
# ═══════════════════════════════════════════════════════════════════════════
# Retrieval for sentiment / RAG
# ═══════════════════════════════════════════════════════════════════════════
 
def get_recent(stock: str | None = None, sector: str | None = None,
               days: int = 1, limit: int = 200):
    """Articles published (or, if no parsed date, downloaded) within the last
    `days`, newest first. Give stock OR sector OR neither (whole corpus)."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = db.query(ScrapedArticle).filter(_effective_date() >= cutoff)
        if stock:
            q = q.filter(ScrapedArticle.related_stock == stock)
        if sector:
            q = (q.join(ArticleSector,
                        ArticleSector.article_id == ScrapedArticle.id)
                  .filter(ArticleSector.sector_name == sector))
        return q.order_by(_effective_date().desc()).limit(limit).all()
    finally:
        db.close()
 
 
# ═══════════════════════════════════════════════════════════════════════════
# Daily cycle, bulk fill loop, Flask startup trigger
# ═══════════════════════════════════════════════════════════════════════════
 
def run_daily(force=False, rss_only=False, drip_only=False,
              minimum=MIN_RECENT_ARTICLES,
              max_stocks=DRIP_MAX_STOCKS_PER_RUN) -> None:
    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if not force and state.get("last_full_cycle_date") == today:
        logger.info("Daily ingestion already completed today.")
        return
    logger.info("=" * 60)
    logger.info(f"Ingestion pass starting (RSS + drip toward {minimum} recent "
                f"articles/stock; NewsAPI is on-demand only)")
    create_db_and_tables()
    db = SessionLocal()
    try:
        alias_index = build_alias_index()
        if not drip_only:
            run_rss(db, alias_index)
        if not rss_only:
            run_drip(db, max_stocks=max_stocks, minimum=minimum)
        state = load_state()   # reload: ensure_* may have updated budget meanwhile
        state["last_full_cycle_date"] = today
        save_state(state)
        stats = db_crud.get_inventory_stats(db)
        logger.info(f"Pass done. Inventory: {stats['total_articles']} articles | "
                    f"by source: {stats['by_source']}")
    finally:
        db.close()
        # Embed whatever un-chunked articles exist right now -- runs even if
        # RSS/drip above raised partway through, and doesn't depend on the
        # cycle having "finished" cleanly. embed_new_articles() only looks
        # for articles with zero rows in article_chunks, so running this
        # every time costs nothing extra when there's nothing new -- it just
        # no-ops fast.
        try:
            import rag
            rag.embed_new_articles()
        except Exception as e:
            logger.error(f"RAG embedding step failed: {e}")
 
        # Same reasoning, same delta-safe pattern, for FinBERT: only articles
        # with finbert_continuous still NULL get scored, so this is a fast
        # no-op on days with nothing new. Without this hook, new articles
        # would keep arriving with a VADER score but no FinBERT score at all
        # until someone remembered to run finbert_benchmark.py by hand.
        try:
            import finbert_benchmark
            finbert_benchmark.score_new_articles()
        except Exception as e:
            logger.error(f"FinBERT scoring step failed: {e}")
 
    logger.info("=" * 60)
 
 
def run_loop(rest_minutes: int, rss_only=False, drip_only=False,
             minimum=MIN_RECENT_ARTICLES,
             max_stocks=DRIP_MAX_STOCKS_PER_RUN) -> None:
    """Bulk fill: repeat passes forever, resting between them so Google's
    rate limiter cools down. Ctrl+C to stop -- every article is committed
    as it's saved, so stopping loses nothing. Safe alongside running Flask
    (WAL mode), but don't start two loops at once."""
    logger.info(f"LOOP MODE: passes toward {minimum} recent articles/stock, "
                f"{rest_minutes} min rest between passes. Ctrl+C to stop.")
    passes = 0
    while True:
        passes += 1
        logger.info(f"----- Loop pass #{passes} -----")
        try:
            run_daily(force=True, rss_only=rss_only, drip_only=drip_only,
                      minimum=minimum, max_stocks=max_stocks)
        except Exception as e:
            logger.error(f"Pass #{passes} crashed (continuing after rest): {e}")
        db = SessionLocal()
        try:
            still = len(stocks_below_recent_minimum(db, minimum))
        finally:
            db.close()
        logger.info(f"Loop status after pass #{passes}: {still} stocks still "
                    f"below {minimum} recent articles. Resting {rest_minutes} min.")
        if still == 0:
            logger.info("All stocks at target -- loop finished, exiting.")
            return
        time.sleep(rest_minutes * 60)
 
 
def maybe_run_daily_on_startup() -> None:
    """Call from app.py. Non-blocking, once per day, reloader-safe if app.py
    already guards WERKZEUG_RUN_MAIN (keep that guard)."""
    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state.get("last_full_cycle_date") == today:
        logger.info("Ingestion already completed today -- not starting.")
        return
    logger.info("Starting daily ingestion in background thread...")
    threading.Thread(target=run_daily, daemon=True,
                     name="ingestion-daily").start()
 
 
# ═══════════════════════════════════════════════════════════════════════════
 
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Ingestion: daily run, bulk fill loop, feed checks, "
                    "on-demand coverage.")
    ap.add_argument("--force", action="store_true",
                    help="run even if already completed today")
    ap.add_argument("--rss-only", action="store_true")
    ap.add_argument("--drip-only", action="store_true")
    ap.add_argument("--check-feeds", action="store_true")
    ap.add_argument("--ensure-sector", type=str, default=None)
    ap.add_argument("--ensure-stock", type=str, default=None)
    ap.add_argument("--minimum", type=int, default=MIN_RECENT_ARTICLES,
                    help="target recent articles per stock for the drip "
                         f"(default {MIN_RECENT_ARTICLES})")
    ap.add_argument("--max-stocks", type=int, default=DRIP_MAX_STOCKS_PER_RUN,
                    help="max under-covered stocks worked per pass "
                         f"(default {DRIP_MAX_STOCKS_PER_RUN})")
    ap.add_argument("--loop", type=int, default=0, metavar="MINUTES",
                    help="bulk fill: repeat passes forever, resting this many "
                         "minutes between them (0 = single pass). "
                         "Exits on its own when every stock hits the target.")
    args = ap.parse_args()
 
    if args.check_feeds:
        check_feeds()
    elif args.ensure_sector:
        print(ensure_sector_coverage(args.ensure_sector))
    elif args.ensure_stock:
        print(ensure_stock_coverage(args.ensure_stock))
    elif args.loop > 0:
        run_loop(args.loop, rss_only=args.rss_only, drip_only=args.drip_only,
                 minimum=args.minimum, max_stocks=args.max_stocks)
    else:
        run_daily(force=args.force, rss_only=args.rss_only,
                  drip_only=args.drip_only, minimum=args.minimum,
                  max_stocks=args.max_stocks)