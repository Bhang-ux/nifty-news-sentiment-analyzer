# gnews_search_backfill.py
"""
Keyless per-stock backfill via Google News SEARCH RSS -- the "unlimited"
source, done the way it still works in 2026.
 
How it works and why it's shaped like this:
  - news.google.com/rss/search?q=<stock> is free, keyless, searchable, and
    returns up to ~100 results per query. Unlimited DISCOVERY.
  - But since mid-2024 the links are encrypted redirects. Resolving each one
    requires a call to Google's internal endpoint (via the googlenewsdecoder
    package), and Google rate-limits that: decode too fast -> HTTP 429.
  - So this runs as a SLOW DRIP: a few dozen stocks per run, seconds between
    decodes, exponential backoff on 429, and it stops gracefully when Google
    gets grumpy. Run it in the evening / overnight; after a few runs, every
    stock that has ANY news coverage reaches the minimum.
 
It only works on stocks below the minimum, always worst-covered first, and
saves through the same save_article_if_new() path (full text via trafilatura,
VADER, multi-sector tagging, source='gnews-search').
 
MUST live in the project root.  Dependencies:
    pip install googlenewsdecoder feedparser trafilatura requests
 
Usage:
    python gnews_search_backfill.py                    # default: ANY NUM stocks
    python gnews_search_backfill.py --max-stocks 60
    python gnews_search_backfill.py --min-articles 5 --decode-delay 4
"""
 
import os
import sys
import time
import argparse
import logging
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
 
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
 
import requests
import feedparser
import trafilatura
from googlenewsdecoder import gnewsdecoder
 
from utils.database_models import SessionLocal, create_db_and_tables, ScrapedArticle
from utils import sentiment_analyzer
from daily_ingestion import build_unique_targets, save_article_if_new
from backfill_ingestion import stocks_below_minimum
 
logger = logging.getLogger("gnews_search_backfill")
 
DECODE_DELAY = 3.0            # seconds between decode calls (be gentle)
MAX_DECODE_ATTEMPTS_PER_STOCK = 12   # candidates tried to reach the target
MAX_CONSECUTIVE_DECODE_FAILS = 8     # across the whole run -> Google says stop
MIN_ARTICLE_CHARS = 400
REQUEST_TIMEOUT = 15
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
 
 
def search_feed_entries(query: str) -> list[dict]:
    """Google News search RSS for a query. Returns raw entries, never raises."""
    url = ("https://news.google.com/rss/search?q="
           + quote(f'"{query}"')
           + "&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return list(feedparser.parse(resp.content).entries)
    except Exception as e:
        logger.warning(f"Search feed failed for '{query}': {e}")
        return []
 
 
def decode_gnews_url(redirect_url: str) -> str | None:
    """Resolve an encrypted news.google.com link to the real article URL."""
    try:
        result = gnewsdecoder(redirect_url, interval=1)
        if isinstance(result, dict) and result.get("status"):
            return result.get("decoded_url")
        logger.debug(f"Decode returned no url: {result}")
        return None
    except Exception as e:
        logger.debug(f"Decode exception: {e}")
        return None
 
 
def backfill_stock(db, stock_name: str, stock_info: dict, need: int,
                   decode_delay: float, fail_streak: list) -> int:
    """Try to save `need` new full-text articles for one stock.
    fail_streak is a single-element list acting as a mutable run-wide counter
    of consecutive decode failures (429 detector)."""
    entries = search_feed_entries(stock_name)
    if not entries:
        return 0
 
    saved = 0
    attempts = 0
    for entry in entries:
        if saved >= need or attempts >= MAX_DECODE_ATTEMPTS_PER_STOCK:
            break
        if fail_streak[0] >= MAX_CONSECUTIVE_DECODE_FAILS:
            break
 
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
 
        attempts += 1
        real_url = decode_gnews_url(link)
        time.sleep(decode_delay)
 
        if not real_url:
            fail_streak[0] += 1
            if fail_streak[0] in (3, 5):          # gentle backoff first
                pause = 30 * fail_streak[0]
                logger.warning(f"{fail_streak[0]} consecutive decode failures "
                               f"-- backing off {pause}s (Google rate limit?)")
                time.sleep(pause)
            continue
        fail_streak[0] = 0
 
        if db.query(ScrapedArticle).filter_by(url=real_url).first():
            continue
 
        text = ""
        try:
            downloaded = trafilatura.fetch_url(real_url)
            if downloaded:
                text = (trafilatura.extract(
                    downloaded, include_comments=False,
                    include_tables=False, favor_recall=True) or "").strip()
        except Exception as e:
            logger.debug(f"Extraction error {real_url}: {e}")
        if len(text) < MIN_ARTICLE_CHARS:
            continue
 
        pub_date = None
        try:
            from email.utils import parsedate_to_datetime
            raw = entry.get("published")
            if raw:
                pub_date = parsedate_to_datetime(raw).astimezone(
                    timezone.utc).replace(tzinfo=None)
        except (ValueError, TypeError):
            pass
 
        vader = sentiment_analyzer.get_vader_sentiment_score(
            f"{title} {text[:3000]}")
        if save_article_if_new(
            db, url=real_url, headline=title, article_text=text,
            pub_date=pub_date, source_domain=urlparse(real_url).netloc,
            vader_score=vader, related_stock=stock_name,
            sector_names=stock_info.get("sectors", []),
            source='gnews-search',
        ):
            saved += 1
            logger.info(f"Saved [{stock_name}] '{title[:70]}'")
    return saved
 
 
def run(max_stocks: int, min_articles: int, decode_delay: float) -> dict:
    create_db_and_tables()
    db = SessionLocal()
    stats = {"stocks_processed": 0, "articles_saved": 0, "stopped_early": False}
    fail_streak = [0]
    try:
        _, all_stocks = build_unique_targets()
        lacking = stocks_below_minimum(db, min_articles)
        logger.info(f"{len(lacking)} stocks below {min_articles}; "
                    f"processing up to {max_stocks} this run "
                    f"(delay {decode_delay}s/decode)")
 
        for stock_name, count in lacking[:max_stocks]:
            if fail_streak[0] >= MAX_CONSECUTIVE_DECODE_FAILS:
                logger.warning("Too many consecutive decode failures -- "
                               "Google is rate-limiting. Stopping this run; "
                               "try again in a few hours.")
                stats["stopped_early"] = True
                break
            need = min_articles - count
            got = backfill_stock(db, stock_name, all_stocks.get(stock_name, {}),
                                 need, decode_delay, fail_streak)
            stats["stocks_processed"] += 1
            stats["articles_saved"] += got
            logger.info(f"'{stock_name}': had {count}, saved {got} more")
 
        still = len(stocks_below_minimum(db, min_articles))
        stats["stocks_still_below_min"] = still
        logger.info(f"Run done: {stats}")
        return stats
    finally:
        db.close()
 
 
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-stocks", type=int, default=100,
                    help="How many under-covered stocks to work this run")
    ap.add_argument("--min-articles", type=int, default=5)
    ap.add_argument("--decode-delay", type=float, default=DECODE_DELAY,
                    help="Seconds between Google decode calls")
    args = ap.parse_args()
    run(args.max_stocks, args.min_articles, args.decode_delay)
 