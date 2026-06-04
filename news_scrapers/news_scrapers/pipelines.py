# news_scrapers/news_scrapers/pipelines.py
import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
import json

# These imports assume your main project (CombinedNiftyNewsApp) is in the Python path
# This was handled by sys.path.insert in settings.py
from utils.database_models import ScrapedArticle, engine as main_app_engine # Use engine from your main app
from utils.sentiment_analyzer import get_vader_sentiment_score # To pre-calculate VADER

logger = logging.getLogger(__name__)

class DatabasePipeline:
    def __init__(self):
        self.SessionLocal = None
        self.session = None

    def open_spider(self, spider):
        # Use the engine from your main application's database_models
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=main_app_engine)
        self.session = self.SessionLocal()
        logger.info("DatabasePipeline: Opened database connection for spider.")

    def close_spider(self, spider):
        if self.session:
            self.session.close()
            logger.info("DatabasePipeline: Closed database connection for spider.")

    def process_item(self, item, spider):
        # Check if URL already exists
        exists = self.session.query(ScrapedArticle).filter_by(url=item.get('url')).first()
        if exists:
            logger.debug(f"Item already in database: {item.get('url')}")
            return item # Drop item if it's a duplicate based on URL

        db_article = ScrapedArticle()
        db_article.url = item.get('url')
        db_article.headline = item.get('headline')
        db_article.article_text = item.get('article_text')
        
        pub_date = item.get('publication_date')
        if pub_date and isinstance(pub_date, datetime):
             # Ensure it's timezone-naive for SQLite
            db_article.publication_date = pub_date.replace(tzinfo=None) if pub_date.tzinfo else pub_date
        elif isinstance(pub_date, str): # Attempt to parse if it's a string
            from utils.newsfetch_lib.news import parse_date_robustly # Assuming this exists and works
            parsed_dt = parse_date_robustly(pub_date) # This should return a naive datetime
            if parsed_dt:
                db_article.publication_date = parsed_dt
            else:
                logger.warning(f"Could not parse publication_date string: {pub_date} for URL: {item.get('url')}")
        
        db_article.download_date = item.get('download_date', datetime.now(timezone.utc)).replace(tzinfo=None)
        db_article.source_domain = item.get('source_domain')
        db_article.language = item.get('language', 'en') # Default to 'en'
        
        authors = item.get('authors')
        if authors and isinstance(authors, list):
            db_article.authors = json.dumps(authors)
            
        keywords = item.get('keywords_extracted')
        if keywords and isinstance(keywords, list):
            db_article.keywords_extracted = json.dumps(keywords)
            
        db_article.summary_generated = item.get('summary_generated')
        db_article.related_sector = item.get('related_sector')
        db_article.related_stock = item.get('related_stock')

        # Pre-calculate VADER score
        if item.get('article_text'):
            db_article.vader_score = get_vader_sentiment_score(item.get('article_text'))

        try:
            self.session.add(db_article)
            self.session.commit()
            logger.info(f"Added to DB: {item.get('url')}")
        except IntegrityError: # Handles cases where URL might still clash if not caught by earlier check
            self.session.rollback()
            logger.warning(f"IntegrityError (likely duplicate URL not caught earlier): {item.get('url')}")
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error adding item to database {item.get('url')}: {e}", exc_info=True)
        return item

# Add this to your news_scrapers/news_scrapers/settings.py:
# ITEM_PIPELINES = {
#    'news_scrapers.pipelines.DatabasePipeline': 300,
# }