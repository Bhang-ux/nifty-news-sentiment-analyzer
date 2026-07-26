# ~/CombinedNiftyNewsApp/utils/db_crud.py
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from .database_models import ScrapedArticle, ArticleSector  # Relative import
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
 
 
# ─── New: structured retrieval, filtering on real columns (not keyword matching) ──
# These are what daily_ingestion.py's saved data is actually meant to be queried
# through -- differentiate by stock, sector, source, and time, in any combination.
 
def tag_article_sectors(db: Session, article_id: int, sector_names: list):
    """
    Records ALL sectors an article is relevant to (not just one) via the
    ArticleSector join table. Safe to call repeatedly -- skips sectors already
    tagged for this article rather than erroring on the unique constraint.
    """
    existing = {row.sector_name for row in
                db.query(ArticleSector).filter(ArticleSector.article_id == article_id).all()}
    added = 0
    for sector_name in sector_names:
        if sector_name and sector_name not in existing:
            db.add(ArticleSector(article_id=article_id, sector_name=sector_name))
            existing.add(sector_name)
            added += 1
    if added:
        db.commit()
    return added
 
 
def get_articles_by_stock(db: Session, stock_name: str, start_date: datetime = None,
                           end_date: datetime = None, source: str = None, limit: int = 50):
    """Articles tagged with this exact stock (via related_stock), optionally filtered
    by date range and/or source ('newsapi' or 'gnews'). Newest first."""
    query = db.query(ScrapedArticle).filter(ScrapedArticle.related_stock == stock_name)
    if start_date:
        query = query.filter(ScrapedArticle.publication_date >= start_date)
    if end_date:
        query = query.filter(ScrapedArticle.publication_date <= end_date)
    if source:
        query = query.filter(ScrapedArticle.source == source)
    return query.order_by(ScrapedArticle.publication_date.desc()).limit(limit).all()
 
 
def get_articles_by_sector(db: Session, sector_name: str, start_date: datetime = None,
                            end_date: datetime = None, source: str = None, limit: int = 50):
    """
    Articles relevant to this sector -- via the ArticleSector join table, so a
    multi-sector stock like HDFC Bank correctly shows up under Nifty Private Bank
    too, not just whichever sector it happened to be tagged with first.
    """
    query = (db.query(ScrapedArticle)
              .join(ArticleSector, ArticleSector.article_id == ScrapedArticle.id)
              .filter(ArticleSector.sector_name == sector_name))
    if start_date:
        query = query.filter(ScrapedArticle.publication_date >= start_date)
    if end_date:
        query = query.filter(ScrapedArticle.publication_date <= end_date)
    if source:
        query = query.filter(ScrapedArticle.source == source)
    return query.order_by(ScrapedArticle.publication_date.desc()).limit(limit).all()
 
 
def get_articles_by_source(db: Session, source: str, start_date: datetime = None,
                            end_date: datetime = None, limit: int = 50):
    """All articles from one specific source ('newsapi' or 'gnews'), newest first."""
    query = db.query(ScrapedArticle).filter(ScrapedArticle.source == source)
    if start_date:
        query = query.filter(ScrapedArticle.publication_date >= start_date)
    if end_date:
        query = query.filter(ScrapedArticle.publication_date <= end_date)
    return query.order_by(ScrapedArticle.publication_date.desc()).limit(limit).all()
 
 
def get_inventory_stats(db: Session):
    """Quick counts for a status view: total articles, by source, and how many
    stocks/sectors currently have zero coverage at all."""
    from sqlalchemy import func
    total = db.query(ScrapedArticle).count()
    by_source = dict(db.query(ScrapedArticle.source, func.count(ScrapedArticle.id))
                      .group_by(ScrapedArticle.source).all())
    stocks_covered = db.query(ScrapedArticle.related_stock).filter(
        ScrapedArticle.related_stock.isnot(None)).distinct().count()
    sectors_covered = db.query(ArticleSector.sector_name).distinct().count()
    return {
        "total_articles": total,
        "by_source": by_source,
        "unique_stocks_covered": stocks_covered,
        "unique_sectors_covered": sectors_covered,
    }
 
# Add other CRUD functions as needed, e.g., for backtesting specific queries