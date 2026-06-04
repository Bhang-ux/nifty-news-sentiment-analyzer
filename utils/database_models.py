# ~/CombinedNiftyNewsApp/utils/database_models.py
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float, Index
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timezone
import os

DEFAULT_DATABASE_URL = "sqlite:///./news_data.db"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(DATABASE_URL)
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
    authors = Column(Text, nullable=True) # Store as JSON string
    keywords_extracted = Column(Text, nullable=True) # Store as JSON string
    summary_generated = Column(Text, nullable=True)
    
    vader_score = Column(Float, nullable=True, index=True)
    llm_sentiment_score = Column(Float, nullable=True, index=True)
    llm_sentiment_label = Column(String, nullable=True)
    llm_analysis_json = Column(Text, nullable=True) # Store full Gemini JSON response

    related_sector = Column(String, nullable=True, index=True)
    related_stock = Column(String, nullable=True, index=True) # Ticker or name

    __table_args__ = (
        Index('ix_scraped_articles_pub_date_domain_headline', 'publication_date', 'source_domain', 'headline'),
    )

def create_db_and_tables():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    print(f"Attempting to create database and tables at {DATABASE_URL}...")
    create_db_and_tables()
    print("Database and tables should be created if they didn't exist.")