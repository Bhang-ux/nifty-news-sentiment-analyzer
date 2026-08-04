# ~/CombinedNiftyNewsApp/utils/database_models.py
from sqlalchemy import (create_engine, Column, Integer, String, Text, DateTime, Float,
                         Index, ForeignKey, inspect, text, event)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime, timezone
import os
import logging
 
logger = logging.getLogger(__name__)
 
# Anchor the DB path to the project root (one level up from utils/), regardless
# of what directory the process was actually launched from. Without this,
# app.py and daily_ingestion.py can silently create two separate DB files
# if they're ever started from different working directories.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATABASE_URL = f"sqlite:///{os.path.join(_PROJECT_ROOT, 'news_data.db')}"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
 
# check_same_thread=False: REQUIRED now that ingestion can run in a background
# thread (triggered from app.py on startup) while Flask's own request threads
# also use this same engine -- without this, SQLite raises immediately the first
# time a different thread touches a connection than the one that created it.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
 
 
@event.listens_for(engine, "connect")
def _set_sqlite_wal_mode(dbapi_connection, connection_record):
    """WAL mode lets one writer and multiple readers work concurrently without
    'database is locked' errors -- matters now that Flask and a background
    ingestion thread can both be hitting the DB around the same time."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
 
 
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
 
 
class ScrapedArticle(Base):
    __tablename__ = "scraped_articles"
 
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True, nullable=False)
    headline = Column(Text, nullable=True)
    article_text = Column(Text, nullable=True)
    publication_date = Column(DateTime, index=True, nullable=True)
    download_date = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    source_domain = Column(String, index=True, nullable=True)
    language = Column(String, nullable=True)
    authors = Column(Text, nullable=True)  # Store as JSON string
    keywords_extracted = Column(Text, nullable=True)  # Store as JSON string
    summary_generated = Column(Text, nullable=True)
 
    vader_score = Column(Float, nullable=True, index=True)
    llm_sentiment_score = Column(Float, nullable=True, index=True)
    llm_sentiment_label = Column(String, nullable=True)
    llm_analysis_json = Column(Text, nullable=True)  # Store full Gemini JSON response
 
    # FinBERT (Phase 2) -- separate from VADER/Gemini above. finbert_label uses
    # FinBERT's own casing ('positive'/'negative'/'neutral') at storage time,
    # normalized to Title Case only when compared against VADER's labels.
    # finbert_score = confidence of the WINNING label only (0 to 1, direction-less).
    # finbert_continuous = P(positive) - P(negative), range -1 to +1 -- the
    # actual equivalent to VADER's compound score, needed for Day 6's backtest
    # correlation (can't correlate returns against a discrete label).
    finbert_label = Column(String, nullable=True, index=True)
    finbert_score = Column(Float, nullable=True)
    finbert_continuous = Column(Float, nullable=True, index=True)
 
    # Kept for backward compatibility with existing code that reads these directly
    # (e.g. a sector-level article's "primary" sector, or a quick single-value check).
    # For the authoritative, complete stock<->sector relationship, use the
    # ArticleSector join table below via db_crud's sector-aware retrieval functions --
    # a stock like HDFC Bank genuinely belongs to 3 sectors, and this single column
    # can only ever hold one of them.
    related_sector = Column(String, nullable=True, index=True)
    related_stock = Column(String, nullable=True, index=True)  # Ticker or name
 
    # Where this article actually came from -- 'newsapi' or 'gnews'. Nullable because
    # articles saved before this column existed won't have it (see migration below).
    source = Column(String, nullable=True, index=True)
 
    sectors = relationship("ArticleSector", back_populates="article", cascade="all, delete-orphan")
 
    __table_args__ = (
        Index('ix_scraped_articles_pub_date_domain_headline', 'publication_date', 'source_domain', 'headline'),
    )
 
 
class ArticleSector(Base):
    """
    Many-to-many: one article can genuinely belong to multiple sectors
    (a stock like HDFC Bank sits in Nifty Bank, Nifty Private Bank, and
    Nifty Services Sector simultaneously). This table is the authoritative
    source for "which sectors is this article relevant to" -- ScrapedArticle.related_sector
    only ever holds one for backward compatibility.
    """
    __tablename__ = "article_sectors"
 
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("scraped_articles.id"), nullable=False, index=True)
    sector_name = Column(String, nullable=False, index=True)
 
    article = relationship("ScrapedArticle", back_populates="sectors")
 
    __table_args__ = (
        Index('ix_article_sector_unique', 'article_id', 'sector_name', unique=True),
    )
 
 
def _migrate_add_missing_columns():
    """
    SQLAlchemy's create_all() only creates tables that don't exist yet -- it will
    NOT add a new column to a table that already exists (like `source` on an
    existing scraped_articles table from before this column was added). This
    does that one safe, additive, idempotent migration so existing data/DB
    files aren't lost or need manual recreation.
    """
    inspector = inspect(engine)
    if "scraped_articles" not in inspector.get_table_names():
        return  # fresh DB, create_all() will build everything correctly, nothing to migrate
    existing_columns = {col["name"] for col in inspector.get_columns("scraped_articles")}
    if "source" not in existing_columns:
        logger.info("Migrating: adding 'source' column to scraped_articles (existing DB, additive, safe).")
        with engine.begin() as conn:  # begin() auto-commits on success, auto-rolls-back on error --
            conn.execute(text("ALTER TABLE scraped_articles ADD COLUMN source VARCHAR"))  # works on SQLAlchemy 1.4 and 2.0
    if "finbert_label" not in existing_columns:
        logger.info("Migrating: adding 'finbert_label'/'finbert_score' columns to scraped_articles.")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE scraped_articles ADD COLUMN finbert_label VARCHAR"))
            conn.execute(text("ALTER TABLE scraped_articles ADD COLUMN finbert_score FLOAT"))
    if "finbert_continuous" not in existing_columns:
        logger.info("Migrating: adding 'finbert_continuous' column to scraped_articles.")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE scraped_articles ADD COLUMN finbert_continuous FLOAT"))
 
 
def create_db_and_tables():
    _migrate_add_missing_columns()
    Base.metadata.create_all(bind=engine)
 
 
if __name__ == "__main__":
    print(f"Attempting to create database and tables at {DATABASE_URL}...")
    create_db_and_tables()
    print("Database and tables should be created if they didn't exist.")