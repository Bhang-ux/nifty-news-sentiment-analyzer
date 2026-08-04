# rescale_vader.py
"""
Recomputes vader_score for every article using the EXACT SAME text window
FinBERT uses -- reuses finbert_benchmark.py's own _prepare_text() function
directly (not a re-implementation), so this is genuinely the same string,
not just "the same character count."
 
Found via the H.G. Infra case: VADER was scored on the first 3000 chars
(ingestion.py's _vader()), FinBERT only on the first 500 -- VADER was
picking up unrelated trailing boilerplate ("Latest events" section with
other quarters' summaries) that FinBERT never saw. This makes both models
score the same input, so any remaining disagreement is genuinely about
model behavior, not input mismatch.
 
WARNING: this OVERWRITES vader_score for every article in the DB. That
column is also read by the sector/stock-analysis Flask routes elsewhere in
the app -- this changes those numbers too, not just the FinBERT comparison.
Run once, deliberately. No backup of the old values is kept.
 
Usage: python rescale_vader.py
"""
 
import os
import sys
import logging
 
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
 
from utils.database_models import SessionLocal, create_db_and_tables, ScrapedArticle
from utils.sentiment_analyzer import get_vader_sentiment_score
from finbert_benchmark import _prepare_text  # reuse FinBERT's exact window logic
 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("rescale_vader")
 
BATCH_SIZE = 200
 
 
def rescale_all_vader_scores(batch_size: int = BATCH_SIZE) -> int:
    create_db_and_tables()
    db = SessionLocal()
    try:
        articles = db.query(ScrapedArticle).all()
        logger.info(f"Rescaling VADER score for {len(articles)} articles "
                    f"to match FinBERT's window...")
 
        for i, a in enumerate(articles):
            text = _prepare_text(a.headline, a.article_text)
            a.vader_score = get_vader_sentiment_score(text)
            if (i + 1) % batch_size == 0:
                db.commit()
                logger.info(f"  {i + 1}/{len(articles)} rescaled")
 
        db.commit()
        logger.info(f"Done. {len(articles)} VADER scores rescaled to the 500-char window.")
        return len(articles)
    finally:
        db.close()
 
 
if __name__ == "__main__":
    rescale_all_vader_scores()