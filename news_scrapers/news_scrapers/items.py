# news_scrapers/news_scrapers/items.py
import scrapy

class NewsArticleItem(scrapy.Item):
    url = scrapy.Field()
    headline = scrapy.Field()
    article_text = scrapy.Field()
    publication_date = scrapy.Field() # Store as datetime object initially
    download_date = scrapy.Field()    # Store as datetime object
    source_domain = scrapy.Field()
    authors = scrapy.Field()          # List of strings
    keywords_extracted = scrapy.Field() # List of strings
    summary_generated = scrapy.Field() # If parsed directly
    related_sector = scrapy.Field()
    related_stock = scrapy.Field()
    language = scrapy.Field()