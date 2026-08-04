# backtest.py
"""
Day 6: per stock, does sentiment(t) predict return(t+1)?

Two separate series per stock -- VADER's and FinBERT's -- correlated
independently against the SAME next-day return series, so the two numbers
are directly comparable: does the domain-specific transformer's sentiment
carry more predictive signal than the generic lexicon's?

Methodology, deliberately spelled out (these are the two traps the guide
flags, and this file exists specifically to avoid both):
  1. RETURNS, not price levels. Prices trend; correlating sentiment against
     a drifting series produces fake correlation from shared trend, not
     genuine predictive signal. return(t) = (close(t)-close(t-1))/close(t-1).
  2. LAG: sentiment(t) vs return(t+1), not same-day. Same-day mostly
     measures news REACTING to a price move that already happened, not
     predicting one. The shift(-1) below is what actually encodes this.

Filters (per the guide): stocks need >=MIN_ARTICLES articles across the
window (a correlation from 3 data points is noise, not a finding), AND
average daily volume above MIN_AVG_VOLUME (a real, data-driven liquidity
check -- not a hardcoded "which stocks are liquid" list).

Known, stated limitation: sentiment is grouped by calendar publication
date, then inner-joined against the trading-day return index. An article
published on a Saturday has no Monday-mapping here -- it simply won't
align with any trading day and drops out of that stock's series. Worth
naming as a limitation in the write-up, not silently ignoring.

Realistic expectation, per the guide: published news-sentiment correlations
run r=0.05-0.3. A number near 0.8 is a red flag, not a win.

Usage:
  python backtest.py                    # full corpus, all qualifying stocks
  python backtest.py --stock "TCS"      # single stock, verbose detail
"""

from __future__ import annotations

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from scipy.stats import pearsonr
import yfinance as yf

from sqlalchemy import func
from utils.database_models import SessionLocal, ScrapedArticle
import ingestion  # reuse build_unique_targets() for the stock list

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("backtest")

MIN_ARTICLES = 10         # relaxed from the guide's 15 -- corpus is still young
                          # (max ~13 article-days on the best-covered stock as of
                          # early Aug 2026); revisit and raise as ingestion accumulates.
MIN_AVG_VOLUME = 100_000  # shares/day -- real, data-driven liquidity filter
LOOKBACK_DAYS = 365        # backtest window

TICKER_MAP_FILE = os.path.join(PROJECT_ROOT, "ticker_map.json")
_ticker_map = None


def _load_ticker_map() -> dict:
    """
    related_stock holds full company names, not ticker symbols -- yfinance
    treats spaces as separators between MULTIPLE tickers, so a naive
    f"{name}.NS" transform silently mangles any multi-word company name
    into garbage. resolve_tickers.py builds this verified mapping; run it
    once before backtesting. Stocks missing from the map are skipped here
    rather than guessed.
    """
    global _ticker_map
    if _ticker_map is None:
        if not os.path.exists(TICKER_MAP_FILE):
            logger.warning(f"{TICKER_MAP_FILE} not found -- run resolve_tickers.py first. "
                          f"Falling back to naive name-to-ticker (will fail on multi-word names).")
            _ticker_map = {}
        else:
            with open(TICKER_MAP_FILE) as f:
                _ticker_map = json.load(f)
            logger.info(f"Loaded {len(_ticker_map)} resolved tickers from {TICKER_MAP_FILE}")
    return _ticker_map


def _effective_date():
    return func.coalesce(ScrapedArticle.publication_date, ScrapedArticle.download_date)


def get_daily_sentiment_series(stock_name: str, score_column: str,
                               start_date, end_date) -> pd.Series:
    """
    Groups all of a stock's articles by publication date, averages the given
    score column (vader_score or finbert_continuous) per day. Multiple
    same-day articles collapse into one daily number -- this IS the daily
    sentiment series, not per-article scores.
    """
    db = SessionLocal()
    try:
        col = getattr(ScrapedArticle, score_column)
        rows = (db.query(_effective_date().label("date"), col.label("score"))
                  .filter(ScrapedArticle.related_stock == stock_name,
                          col.isnot(None),
                          _effective_date() >= start_date,
                          _effective_date() <= end_date)
                  .all())
    finally:
        db.close()

    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows, columns=["date", "score"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    daily = df.groupby("date")["score"].mean()
    daily.index = pd.to_datetime(daily.index)
    return daily.sort_index()


def get_adjusted_close_returns(ticker: str, start_date, end_date) -> tuple[pd.Series, pd.Series]:
    """
    Returns (returns_series, volume_series), both indexed by trading date.
    auto_adjust=True -- adjusted closes, per the guide (raw closes distort
    around splits/dividends).

    `ticker` here is actually the STOCK NAME (e.g. "Zensar Technologies"),
    resolved to a real symbol via ticker_map.json -- built by
    resolve_tickers.py. Never falls back to guessing here; a name missing
    from the map returns empty series, and the caller (backtest_stock)
    correctly skips it rather than risk another silent multi-ticker mangle.
    """
    ticker_map = _load_ticker_map()
    resolved = ticker_map.get(ticker)
    if not resolved:
        logger.debug(f"No resolved ticker for '{ticker}' -- run resolve_tickers.py. Skipping.")
        return pd.Series(dtype=float), pd.Series(dtype=float)

    df = yf.download(resolved, start=start_date, end=end_date + timedelta(days=1),
                     progress=False, auto_adjust=True)
    if df.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    if isinstance(df.columns, pd.MultiIndex):  # yfinance sometimes returns multi-index columns
        df.columns = df.columns.get_level_values(0)

    # .squeeze() defends against yfinance occasionally returning a 1-column
    # DataFrame instead of a Series for certain tickers -- without this,
    # volume.mean() can return a Series instead of a scalar, and comparing
    # that against min_avg_volume raises "truth value of a Series is
    # ambiguous" (the exact crash seen on 'Max Healthcare' in the first run).
    close = df["Close"].squeeze()
    volume = df["Volume"].squeeze()
    returns = close.pct_change(fill_method=None).dropna()  # (close_t - close_t-1) / close_t-1
    return returns, volume


def backtest_stock(stock_name: str, start_date, end_date,
                   min_articles: int = MIN_ARTICLES,
                   min_avg_volume: int = MIN_AVG_VOLUME) -> dict | None:
    """
    Returns None if the stock doesn't pass the article-count or liquidity
    filter -- these are exclusions, not failures, and are expected for most
    of a 252-stock universe on any given window.
    """
    vader_series = get_daily_sentiment_series(stock_name, "vader_score", start_date, end_date)
    finbert_series = get_daily_sentiment_series(stock_name, "finbert_continuous", start_date, end_date)

    n_articles = len(vader_series)  # one row per DAY with articles, not per article --
    if n_articles < min_articles:   # a rough but reasonable proxy per the guide's spirit
        return None

    returns, volume = get_adjusted_close_returns(stock_name, start_date, end_date)
    if returns.empty:
        return None
    if volume.mean() < min_avg_volume:
        return None

    # THE lag: shift(-1) moves tomorrow's return to today's index position,
    # so aligning sentiment(t) against this shifted series IS sentiment(t) vs
    # return(t+1) -- not same-day. This line is the entire methodology.
    returns_next_day = returns.shift(-1)

    def _correlate(sentiment_series: pd.Series) -> dict | None:
        combined = pd.concat([sentiment_series, returns_next_day], axis=1,
                             join="inner").dropna()
        combined.columns = ["sentiment", "return_t plus 1"]
        if len(combined) < 5:  # need at minimum a handful of aligned points for a meaningful r
            return None
        r, p = pearsonr(combined["sentiment"], combined["return_t plus 1"])
        return {"r": round(float(r), 4), "p_value": round(float(p), 4), "n_days": len(combined)}

    vader_result = _correlate(vader_series)
    finbert_result = _correlate(finbert_series)
    if vader_result is None and finbert_result is None:
        return None

    return {
        "stock": stock_name,
        "n_articles_days": n_articles,
        "avg_volume": int(volume.mean()),
        "vader": vader_result,
        "finbert": finbert_result,
    }


def run_backtest(stocks: list[str] | None = None, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=lookback_days)

    if stocks is None:
        _, all_stocks = ingestion.build_unique_targets()
        stocks = list(all_stocks.keys())

    results = []
    skipped = 0
    for i, stock_name in enumerate(stocks):
        try:
            result = backtest_stock(stock_name, start_date, end_date)
        except Exception as e:
            logger.warning(f"Backtest failed for '{stock_name}': {e}")
            result = None
        if result is None:
            skipped += 1
        else:
            results.append(result)
        if (i + 1) % 25 == 0:
            logger.info(f"Processed {i+1}/{len(stocks)} stocks "
                       f"({len(results)} qualified, {skipped} skipped)")

    logger.info(f"Backtest done: {len(results)}/{len(stocks)} stocks qualified "
               f"(>= {MIN_ARTICLES} article-days, >= {MIN_AVG_VOLUME:,} avg volume)")
    return results


def print_summary(results: list[dict]) -> None:
    vader_rs = [r["vader"]["r"] for r in results if r["vader"]]
    finbert_rs = [r["finbert"]["r"] for r in results if r["finbert"]]

    print(f"\n=== Backtest Summary: sentiment(t) vs return(t+1) ===")
    print(f"Stocks qualified: {len(results)}")
    print(f"\nVADER:   mean r = {np.mean(vader_rs):.4f}  (n={len(vader_rs)} stocks, "
         f"range {min(vader_rs):.3f} to {max(vader_rs):.3f})" if vader_rs else "VADER:   no qualifying results")
    print(f"FinBERT: mean r = {np.mean(finbert_rs):.4f}  (n={len(finbert_rs)} stocks, "
         f"range {min(finbert_rs):.3f} to {max(finbert_rs):.3f})" if finbert_rs else "FinBERT: no qualifying results")

    if vader_rs and finbert_rs:
        winner = "FinBERT" if abs(np.mean(finbert_rs)) > abs(np.mean(vader_rs)) else "VADER"
        print(f"\nStronger mean |r|: {winner}")

    print(f"\n=== Per-stock detail ===")
    for r in sorted(results, key=lambda x: abs(x["finbert"]["r"]) if x["finbert"] else 0, reverse=True):
        v = f"r={r['vader']['r']} (p={r['vader']['p_value']}, n={r['vader']['n_days']})" if r["vader"] else "n/a"
        f = f"r={r['finbert']['r']} (p={r['finbert']['p_value']}, n={r['finbert']['n_days']})" if r["finbert"] else "n/a"
        print(f"{r['stock']:<30} articles_days={r['n_articles_days']:<4} vol={r['avg_volume']:>10,} "
             f"| VADER {v:<28} | FinBERT {f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", type=str, default=None, help="backtest a single stock only")
    ap.add_argument("--days", type=int, default=LOOKBACK_DAYS, help=f"lookback window (default {LOOKBACK_DAYS})")
    args = ap.parse_args()

    if args.stock:
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=args.days)
        result = backtest_stock(args.stock, start_date, end_date)
        if result is None:
            print(f"'{args.stock}' did not qualify (< {MIN_ARTICLES} article-days, "
                 f"< {MIN_AVG_VOLUME:,} avg volume, or no price data).")
        else:
            print_summary([result])
    else:
        results = run_backtest(lookback_days=args.days)
        print_summary(results)