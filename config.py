import os
from dotenv import load_dotenv

load_dotenv()

# Unique placeholder strings unlikely to match real API keys
NEWSAPI_ORG_API_KEY_PLACEHOLDER = "NEWSAPI_ORG_API_KEY_DEFAULT_PLACEHOLDER_2025_XYZ123"
GEMINI_API_KEY_PLACEHOLDER = "GEMINI_API_KEY_DEFAULT_PLACEHOLDER_2025_ABC789"

# Load actual API keys from .env, fallback to placeholders if not set
NEWSAPI_ORG_API_KEY = os.getenv("87de43db6453481c965b10abc58375b6", NEWSAPI_ORG_API_KEY_PLACEHOLDER)
GEMINI_API_KEY = os.getenv("AIzaSyANBOTpHkdlpISgG6BLWuUmoKiB8t6ugJo", GEMINI_API_KEY_PLACEHOLDER)
FLASK_SECRET_KEY = os.getenv("ICICIPRU", "DEFAULT_FLASK_SECRET_KEY_2025_RANDOM123")
# Scraper Delays for app.py's on-demand scrape
APP_SCRAPER_SEARCH_DELAY_GOOGLE = 5  # Shorter for on-demand, more risk
APP_SCRAPER_ARTICLE_FETCH_DELAY = 2 # Shorter for on-demand

# Potentially, scraper settings could go here too
SCRAPER_SEARCH_DELAY = 15
SCRAPER_ARTICLE_FETCH_DELAY = 7
SCRAPER_GOOGLE_PAGES = 1
