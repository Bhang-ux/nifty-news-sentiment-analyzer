# news_scrapers/news_scrapers/settings.py

BOT_NAME = "news_scrapers"

SPIDER_MODULES = ["news_scrapers.spiders"]
NEWSPIDER_MODULE = "news_scrapers.spiders"

# Obey robots.txt rules
ROBOTSTXT_OBEY = True # Be a good bot

# Configure a delay for requests for the same website (seconds)
DOWNLOAD_DELAY = 3  # Start with 3 seconds, adjust as needed
CONCURRENT_REQUESTS_PER_DOMAIN = 2 # Be gentle

# --- Playwright Settings ---
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor" # Important for Playwright
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True, # Set to False for debugging spiders
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1920,1080"
    ]
}
PLAYWRIGHT_BROWSER_TYPE = "chromium" # Or 'firefox', 'webkit'

# It's good to set a default User-Agent
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'

# Optional: Configure item pipelines if you want to process items through Scrapy pipelines
# ITEM_PIPELINES = {
#    'news_scrapers.pipelines.DatabasePipeline': 300, # Example
# }

# Add path to your main project utils if spiders need them
# This allows spiders to import your database models etc.
import sys
import os
# Assuming CombinedNiftyNewsApp is the parent of news_scrapers project dir
# Adjust if your structure is different
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)