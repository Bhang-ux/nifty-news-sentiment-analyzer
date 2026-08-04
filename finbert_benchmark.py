# finbert_benchmark.py
"""
Day 5: run FinBERT on the corpus, store label+score per article, compute
VADER-vs-FinBERT agreement, surface real disagreement examples.
 
Explicitly INFERENCE only -- ProsusAI/finbert is a pre-trained model, loaded
and run as-is. No training, no fine-tuning happens here.
 
Runs on headline + first ~500 chars of article_text per the guide's spec --
not the whole article. Batched, CPU is fine (this can run overnight for a
full corpus backfill; subsequent runs only score newly-arrived articles,
same delta pattern as rag.py's embed_new_articles()).
 
Usage:
  python finbert_benchmark.py              # score every un-scored article
  python finbert_benchmark.py --agreement  # skip scoring, just report
                                            # agreement + disagreements on
                                            # whatever's already scored
"""
 
from __future__ import annotations
 
import os
import sys
import argparse
import logging
from datetime import datetime
 
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
 
from sqlalchemy import text as sql_text
from utils.database_models import SessionLocal, create_db_and_tables, engine, ScrapedArticle
from utils.sentiment_analyzer import get_sentiment_label_from_score, prepare_scoring_text
 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("finbert_benchmark")
 
FINBERT_MODEL = "ProsusAI/finbert"
BATCH_SIZE = 32
 
_pipeline = None
 
 
def _get_pipeline():
    """Lazy-loaded so this module imports cleanly even before transformers/torch
    are installed -- same reasoning as rag.py's _get_model()."""
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline
        logger.info(f"Loading {FINBERT_MODEL} (first call only, CPU)...")
        _pipeline = pipeline("sentiment-analysis", model=FINBERT_MODEL, device=-1)  # device=-1 = CPU
    return _pipeline
 
 
# _prepare_text is now just prepare_scoring_text from sentiment_analyzer --
# kept as an alias so nothing else importing _prepare_text from this module
# (e.g. rescale_vader.py) breaks. Both VADER (ingestion.py) and FinBERT use
# the exact same function now, not two independently-maintained copies of
# the same window logic -- that mismatch is what caused the H.G. Infra case.
_prepare_text = prepare_scoring_text
 
 
def score_batch(texts: list[str]) -> list[tuple[str, float, float]]:
    """
    Returns [(label, score, continuous), ...].
      label: Title Case ('Positive'/'Negative'/'Neutral') -- normalized to match
             VADER's own label convention (get_sentiment_label_from_score).
      score: confidence of the winning label only (0 to 1, direction-less).
      continuous: P(positive) - P(negative), range -1 to +1 -- the actual
             equivalent to VADER's compound score, needed to correlate against
             returns in the Day 6 backtest (a discrete label can't be correlated).
 
    top_k=None is the fix -- without it, the pipeline silently discards two of
    the three class probabilities and only returns the winning label, which is
    fine for reporting a label but useless for building a continuous score.
    """
    pipe = _get_pipeline()
    all_scores = pipe(texts, truncation=True, max_length=512, batch_size=BATCH_SIZE, top_k=None)
 
    results = []
    for scores in all_scores:
        # scores is a list of 3 dicts: [{'label': 'positive', 'score': 0.7}, {'label': 'negative', 'score': 0.2}, {'label': 'neutral', 'score': 0.1}]
        by_label = {s["label"].lower(): s["score"] for s in scores}
        pos, neg, neu = by_label.get("positive", 0.0), by_label.get("negative", 0.0), by_label.get("neutral", 0.0)
        winning_label = max(by_label, key=by_label.get).capitalize()
        winning_score = max(by_label.values())
        continuous = pos - neg
        results.append((winning_label, float(winning_score), float(continuous)))
    return results
 
 
def score_new_articles(batch_size: int = BATCH_SIZE) -> int:
    """
    Delta scoring: articles with finbert_continuous still NULL -- deliberately
    NOT finbert_label, so articles already scored by an older version of this
    script (label+score only, before the top_k fix) get correctly picked up
    for re-scoring to fill in the new continuous column, rather than being
    skipped as "already done."
    """
    create_db_and_tables()
    db = SessionLocal()
    try:
        to_score = db.query(ScrapedArticle).filter(ScrapedArticle.finbert_continuous.is_(None)).all()
        logger.info(f"score_new_articles: {len(to_score)} articles need FinBERT scoring")
        if not to_score:
            return 0
 
        total_scored = 0
        for i in range(0, len(to_score), batch_size):
            chunk = to_score[i:i + batch_size]
            texts = [_prepare_text(a.headline, a.article_text) for a in chunk]
            texts = [t if t.strip() else "no content available" for t in texts]
            results = score_batch(texts)
 
            for article, (label, score, continuous) in zip(chunk, results):
                article.finbert_label = label
                article.finbert_score = score
                article.finbert_continuous = continuous
            db.commit()
            total_scored += len(chunk)
            logger.info(f"score_new_articles: {min(i + batch_size, len(to_score))}/{len(to_score)} scored")
 
        logger.info(f"score_new_articles: done, {total_scored} articles scored")
        return total_scored
    finally:
        db.close()
 
 
def compute_agreement(sample_disagreements: int = 5) -> dict:
    """
    VADER's continuous score -> label via the SAME threshold function the rest
    of the app already uses (get_sentiment_label_from_score, +-0.05), not a
    new one invented here -- keeps VADER's label meaning consistent everywhere
    it's used in this project.
    """
    db = SessionLocal()
    try:
        rows = (db.query(ScrapedArticle)
                  .filter(ScrapedArticle.finbert_label.isnot(None),
                          ScrapedArticle.vader_score.isnot(None))
                  .all())
        if not rows:
            logger.warning("No articles have both VADER and FinBERT scores yet.")
            return {"total": 0, "agree": 0, "agreement_pct": 0.0, "disagreements": []}
 
        agree = 0
        disagreements = []
        for a in rows:
            vader_label = get_sentiment_label_from_score(a.vader_score)
            if vader_label == a.finbert_label:
                agree += 1
            else:
                disagreements.append({
                    "id": a.id,
                    "headline": a.headline,
                    "vader_score": round(a.vader_score, 3),
                    "vader_label": vader_label,
                    "finbert_label": a.finbert_label,
                    "finbert_score": round(a.finbert_score, 3),
                    "url": a.url,
                })
 
        agreement_pct = round(agree / len(rows) * 100, 1)
        return {
            "total": len(rows),
            "agree": agree,
            "agreement_pct": agreement_pct,
            "disagreements": disagreements[:sample_disagreements],
            "all_disagreement_count": len(disagreements),
        }
    finally:
        db.close()
 
 
def print_report(result: dict) -> None:
    print(f"\n=== VADER vs FinBERT Agreement ===")
    print(f"Total articles compared: {result['total']}")
    print(f"Agreement: {result['agree']}/{result['total']} ({result['agreement_pct']}%)")
    print(f"Total disagreements: {result.get('all_disagreement_count', 0)}")
    print(f"\n=== Sample disagreements (for the 'explain 5' write-up) ===")
    for d in result["disagreements"]:
        print(f"\nid={d['id']} | {d['headline'][:90]}")
        print(f"  VADER:   {d['vader_label']} (score={d['vader_score']})")
        print(f"  FinBERT: {d['finbert_label']} (score={d['finbert_score']})")
        print(f"  url: {d['url']}")
 
 
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agreement", action="store_true",
                    help="skip scoring, just report agreement on what's already scored")
    args = ap.parse_args()
 
    if not args.agreement:
        score_new_articles()
 
    result = compute_agreement()
    print_report(result)