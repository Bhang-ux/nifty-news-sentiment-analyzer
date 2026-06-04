# ~/CombinedNiftyNewsApp/utils/db_crud.py
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from .database_models import ScrapedArticle # Relative import
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

def get_articles_for_analysis(db: Session, start_date: datetime, end_date: datetime, 
                              target_keywords: list, source_domains_filter: list = None, 
                              limit: int = 50):
    """
    Fetches articles for sentiment analysis based on keywords in headline or article_text,
    and optionally filters by source domains.
    """
    logger.debug(f"DB CRUD: Fetching articles for analysis. Dates: {start_date} to {end_date}. Keywords: {target_keywords}. Domains: {source_domains_filter}. Limit: {limit}")
    
    query = db.query(ScrapedArticle).filter(
        ScrapedArticle.publication_date >= start_date,
        ScrapedArticle.publication_date <= end_date,
        ScrapedArticle.article_text != None,
        ScrapedArticle.article_text != ""
    )

    if source_domains_filter:
        domain_conditions = [ScrapedArticle.source_domain.ilike(f"%{domain}%") for domain in source_domains_filter]
        query = query.filter(or_(*domain_conditions))

    if target_keywords:
        keyword_conditions = []
        for kw in target_keywords:
            keyword_conditions.append(ScrapedArticle.headline.ilike(f"%{kw}%"))
            keyword_conditions.append(ScrapedArticle.article_text.ilike(f"%{kw}%"))
        if keyword_conditions:
            query = query.filter(or_(*keyword_conditions))
    
    articles = query.order_by(ScrapedArticle.publication_date.desc()).limit(limit).all()
    logger.debug(f"DB CRUD: Found {len(articles)} articles matching criteria.")
    return articles


def update_article_sentiment_scores(db: Session, article_url: str, 
                                   vader_score: float = None, 
                                   llm_sentiment_score: float = None, 
                                   llm_sentiment_label: str = None, 
                                   llm_analysis_json: str = None,
                                   related_sector: str = None, 
                                   related_stock: str = None):
    article = db.query(ScrapedArticle).filter(ScrapedArticle.url == article_url).first()
    if article:
        updated = False
        if vader_score is not None: 
            article.vader_score = vader_score
            updated = True
        if llm_sentiment_score is not None: 
            article.llm_sentiment_score = llm_sentiment_score
            updated = True
        if llm_sentiment_label is not None: 
            article.llm_sentiment_label = llm_sentiment_label
            updated = True
        if llm_analysis_json is not None: 
            article.llm_analysis_json = llm_analysis_json
            updated = True
        if related_sector is not None and not article.related_sector: # Only set if not already set, or update if different
            article.related_sector = related_sector
            updated = True
        if related_stock is not None and not article.related_stock:
            article.related_stock = related_stock
            updated = True
        
        if updated:
            try:
                db.commit()
                logger.info(f"DB CRUD: Updated sentiment for article: {article_url}")
                return True
            except Exception as e:
                db.rollback()
                logger.error(f"DB CRUD: Error committing sentiment update for {article_url}: {e}")
                return False
    else:
        logger.warning(f"DB CRUD: Article not found for sentiment update: {article_url}")
    return False

def get_article_by_url(db: Session, url: str):
    return db.query(ScrapedArticle).filter(ScrapedArticle.url == url).first()

# Add other CRUD functions as needed, e.g., for backtesting specific queries