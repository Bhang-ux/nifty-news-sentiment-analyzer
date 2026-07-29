# rss_ingestion.py
"""
Quota-free, full-content article ingestion from Indian financial publisher RSS
feeds. Third source alongside NewsAPI ('newsapi') and GNews ('gnews') --
articles are saved through the SAME save_article_if_new() path as those two,
with source='rss:<publisher>', full multi-sector tagging via ArticleSector,
VADER scored at ingest.
 
Why this exists:
  - Google News RSS links are encrypted redirects (since 2024); trafilatura on
    them extracts nothing -- that's why the GNews fallback saves 0 articles.
  - NewsAPI free tier truncates content to ~200 chars -- useless for RAG.
  - Publisher RSS feeds give DIRECT article URLs; trafilatura on those returns
    full text. No API keys, no daily budgets.
 
MUST live in the project root (same directory as daily_ingestion.py).
 
Dependencies:  pip install feedparser trafilatura requests
 
Usage:
    python rss_ingestion.py --check-feeds      # verify feeds are alive
    python rss_ingestion.py --limit 20         # small test run
    python rss_ingestion.py                    # full run
    python rss_ingestion.py --keep-unmatched   # also save finance articles that
                                               # name none of your 274 targets
                                               # (bigger RAG corpus, untagged)
 
Or from daily_ingestion.run_ingestion_cycle():
    from rss_ingestion import run_rss_ingestion
    run_rss_ingestion()
"""
 
from __future__ import annotations
 
import argparse
import logging
import re
import sys
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
 
import feedparser
import requests
import trafilatura
 
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
 
log = logging.getLogger("rss_ingestion")
 
# ---------------------------------------------------------------------------
# Feed registry (all verified alive 2026-07-26; Business Standard and
# Financial Express removed -- they block scripted requests).
# ---------------------------------------------------------------------------
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
 
MIN_ARTICLE_CHARS = 400          # below this, extraction is considered failed
REQUEST_TIMEOUT = 15
POLITE_DELAY = 1.0               # seconds between article-page fetches
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
 
 
@dataclass
class Article:
    url: str
    title: str
    published_at: datetime | None
    source: str                       # 'rss:<publisher>'
    text: str = ""
    matched_targets: list[str] = field(default_factory=list)
 
 
# ---------------------------------------------------------------------------
# Feed fetching / parsing
# ---------------------------------------------------------------------------
 
def fetch_feed(url: str) -> list[dict]:
    """Fetch one RSS feed; returns list of raw entries. Never raises."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        if parsed.bozo and not parsed.entries:
            log.warning("Feed unparseable: %s (%s)", url, parsed.bozo_exception)
            return []
        return list(parsed.entries)
    except Exception as exc:
        log.warning("Feed fetch failed: %s (%s)", url, exc)
        return []
 
 
def parse_entry(entry: dict, publisher: str) -> Article | None:
    url = (entry.get("link") or "").strip()
    title = (entry.get("title") or "").strip()
    if not url or not title:
        return None
    if "news.google.com" in url:      # never ingest redirect links
        return None
 
    published = None
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                published = parsedate_to_datetime(raw)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                break
            except (TypeError, ValueError):
                continue
    return Article(url=url, title=title, published_at=published,
                   source=f"rss:{publisher}")
 
 
# ---------------------------------------------------------------------------
# Full-text extraction
# ---------------------------------------------------------------------------
 
def extract_full_text(url: str) -> str:
    """Full article text via trafilatura, or '' on failure. Never raises."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
        return (text or "").strip()
    except Exception as exc:
        log.warning("Extraction error for %s: %s", url, exc)
        return ""
 
 
# ---------------------------------------------------------------------------
# Target matching (stock/sector tagging) -- word-boundary regex so short
# tickers like 'TCS' don't false-match inside other words.
# ---------------------------------------------------------------------------
 
def build_alias_index(targets: dict[str, list[str]]) -> list[tuple[re.Pattern, str]]:
    """
    targets: {canonical_name: [alias, ...]}
    Returns [(compiled_pattern, canonical_name)], longest aliases first so
    'HDFC Bank' matches before 'HDFC'.
    """
    raw: list[tuple[str, str]] = []
    for canonical, aliases in targets.items():
        for alias in {canonical, *aliases}:
            alias = alias.strip()
            if len(alias) >= 3:
                raw.append((alias, canonical))
    raw.sort(key=lambda p: len(p[0]), reverse=True)
    return [(re.compile(r"(?<!\w)" + re.escape(a) + r"(?!\w)", re.IGNORECASE), c)
            for a, c in raw]
 
 
def match_targets(article: Article, alias_index: list[tuple[re.Pattern, str]],
                  search_body_chars: int = 1500) -> list[str]:
    haystack = article.title + " " + article.text[:search_body_chars]
    hits: list[str] = []
    for pattern, canonical in alias_index:
        if canonical not in hits and pattern.search(haystack):
            hits.append(canonical)
    return hits
 
 
# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
 
def run_rss_ingestion(limit: int | None = None,
                      require_target_match: bool = True) -> dict:
    stats = {"feeds_ok": 0, "feeds_dead": 0, "entries_seen": 0,
             "skipped_bad_entry": 0, "skipped_duplicate": 0,
             "skipped_empty_text": 0, "skipped_no_target": 0,
             "saved": 0, "per_publisher": {}}
 
    targets = load_targets()
    alias_index = build_alias_index(targets)
    seen_this_run: set[str] = set()
    extracted = 0
 
    try:
        for publisher, feed_urls in FEEDS.items():
            pub_saved = 0
            for feed_url in feed_urls:
                entries = fetch_feed(feed_url)
                if entries:
                    stats["feeds_ok"] += 1
                else:
                    stats["feeds_dead"] += 1
                    continue
 
                for entry in entries:
                    stats["entries_seen"] += 1
                    art = parse_entry(entry, publisher)
                    if art is None:
                        stats["skipped_bad_entry"] += 1
                        continue
                    if art.url in seen_this_run or url_exists(art.url):
                        stats["skipped_duplicate"] += 1
                        continue
                    seen_this_run.add(art.url)
 
                    if limit is not None and extracted >= limit:
                        log.info("Extraction limit %d reached, stopping.", limit)
                        stats["per_publisher"][publisher] = pub_saved
                        log.info("RSS ingestion done: %s", stats)
                        return stats
 
                    art.text = extract_full_text(art.url)
                    extracted += 1
                    time.sleep(POLITE_DELAY)
 
                    if len(art.text) < MIN_ARTICLE_CHARS:
                        stats["skipped_empty_text"] += 1
                        log.info("Empty/short extract (%d chars): %s",
                                 len(art.text), art.url)
                        continue
 
                    art.matched_targets = match_targets(art, alias_index)
                    if require_target_match and not art.matched_targets:
                        stats["skipped_no_target"] += 1
                        continue
 
                    try:
                        if persist_article(art):
                            stats["saved"] += 1
                            pub_saved += 1
                            log.info("Saved [%s] '%s' -> %s",
                                     publisher, art.title[:70],
                                     art.matched_targets[:5])
                    except Exception as exc:
                        log.error("DB save failed for %s: %s", art.url, exc)
 
            stats["per_publisher"][publisher] = pub_saved
 
        log.info("RSS ingestion done: %s", stats)
        return stats
    finally:
        close_db()
 
 
def check_feeds() -> None:
    for publisher, feed_urls in FEEDS.items():
        for url in feed_urls:
            entries = fetch_feed(url)
            status = f"OK ({len(entries)} entries)" if entries else "DEAD"
            print(f"[{status:>16}] {publisher:<18} {url}")
 
 
# ---------------------------------------------------------------------------
# Persistence adapter -- wired to this project's existing code.
# Reuses daily_ingestion.save_article_if_new(), so RSS articles get identical
# treatment: dedupe by url, ArticleSector multi-sector tagging, VADER score,
# source column. All heavy imports are lazy (inside functions) to avoid any
# circular-import issues with daily_ingestion.
# ---------------------------------------------------------------------------
 
_db = None                      # one SQLAlchemy session per run
_target_info: dict[str, dict] = {}   # canonical -> {'is_sector': bool, 'sectors': [...]}
 
 
def _get_db():
    global _db
    if _db is None:
        from utils.database_models import SessionLocal, create_db_and_tables
        create_db_and_tables()
        _db = SessionLocal()
    return _db
 
 
def close_db():
    global _db
    if _db is not None:
        _db.close()
        _db = None
 
 
def url_exists(url: str) -> bool:
    from utils.database_models import ScrapedArticle
    db = _get_db()
    return db.query(ScrapedArticle).filter_by(url=url).first() is not None
 
 
def load_targets() -> dict[str, list[str]]:
    """22 sectors + unique stocks from the same config daily_ingestion uses.
    Also records, per target, whether it's a sector and which sectors a stock
    belongs to -- needed when saving."""
    from daily_ingestion import build_unique_targets
    from utils import gemini_utils
 
    sectors, stocks = build_unique_targets()
    targets: dict[str, list[str]] = {}
    for name in sectors:
        kws = gemini_utils.NIFTY_SECTORS_QUERY_CONFIG[name].get("newsapi_keywords", [])
        targets[name] = list(kws)
        _target_info[name] = {"is_sector": True, "sectors": [name]}
    for name, info in stocks.items():
        targets[name] = list(info["keywords"] or [])
        _target_info[name] = {"is_sector": False, "sectors": list(info["sectors"])}
    log.info("Loaded %d targets for matching", len(targets))
    return targets
 
 
def persist_article(article: Article) -> bool:
    """Save via daily_ingestion.save_article_if_new(). Returns True if new.
 
    related_stock is single-valued in the schema, so if an article mentions
    several stocks the first match (longest/most specific alias) wins that
    column -- but sectors from ALL matched stocks get tagged in ArticleSector,
    so sector-level retrieval still finds the article everywhere it belongs.
    """
    from daily_ingestion import save_article_if_new
    from utils import sentiment_analyzer
 
    db = _get_db()
 
    related_stock = None
    sector_names: list[str] = []
    for name in article.matched_targets:
        info = _target_info.get(name)
        if info is None:
            continue
        if info["is_sector"]:
            if name not in sector_names:
                sector_names.append(name)
        else:
            if related_stock is None:
                related_stock = name
            for s in info["sectors"]:
                if s not in sector_names:
                    sector_names.append(s)
 
    vader_score = sentiment_analyzer.get_vader_sentiment_score(
        f"{article.title} {article.text[:3000]}")
 
    pub_date = article.published_at
    if pub_date is not None and pub_date.tzinfo is not None:
        # DB stores naive UTC datetimes (matches daily_ingestion's convention)
        pub_date = pub_date.astimezone(timezone.utc).replace(tzinfo=None)
 
    return save_article_if_new(
        db,
        url=article.url,
        headline=article.title,
        article_text=article.text,
        pub_date=pub_date,
        source_domain=urlparse(article.url).netloc,
        vader_score=vader_score,
        related_stock=related_stock,
        sector_names=sector_names,
        source=article.source,
    )
 
 
# ---------------------------------------------------------------------------
 
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-feeds", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--keep-unmatched", action="store_true")
    args = ap.parse_args()
 
    if args.check_feeds:
        check_feeds()
    else:
        run_rss_ingestion(limit=args.limit,
                          require_target_match=not args.keep_unmatched)