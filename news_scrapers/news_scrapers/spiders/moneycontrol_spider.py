# news_scrapers/news_scrapers/spiders/moneycontrol_spider.py
import scrapy
from scrapy_playwright.page import PageMethod
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
import logging
import re
from dateutil import parser as dateutil_parser # For more flexible date parsing
                                             # Install: pip install python-dateutil

# Assuming your items.py is in the parent directory of spiders (i.e., news_scrapers.items)
from ..items import NewsArticleItem 
# If utils are in the main project root (CombinedNiftyNewsApp/utils/)
# and settings.py correctly adds the project root to sys.path:
from utils.gemini_utils import NIFTY_SECTORS_QUERY_CONFIG # To associate articles

logger = logging.getLogger(__name__)

class MoneycontrolSpider(scrapy.Spider):
    name = "moneycontrol"
    allowed_domains = ["moneycontrol.com"]
    
    custom_settings = {
        "PLAYWRIGHT_LAUNCH_OPTIONS": {
            "headless": True, # Set to False for debugging
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1920,1080"
            ]
        },
        "USER_AGENT": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        "DOWNLOAD_DELAY": 4,       # Increased delay
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1, # Be very gentle
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 5,
        "AUTOTHROTTLE_MAX_DELAY": 60,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
        "LOG_LEVEL": "INFO",
        "RETRY_TIMES": 2, # Retry failed requests (e.g., timeouts)
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 60000, # 60 seconds for Playwright page navigations
        # "CLOSESPIDER_PAGECOUNT": 10, # For testing: stop after 10 pages
        # "CLOSESPIDER_ITEMCOUNT": 50, # For testing: stop after 50 items
    }

    def __init__(self, target_keyword=None, start_date_str=None, end_date_str=None, pages_to_scrape=2, sector_context=None, stock_name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if not target_keyword:
            # If no specific keyword, we might scrape a general section and not filter by keyword initially
            logger.warning("No target_keyword provided. Spider will attempt to scrape a general section.")
            # self.target_keyword = "" # Or some default broad term if needed by URL structure
        self.target_keyword = target_keyword.lower() if target_keyword else ""
        self.pages_to_scrape = int(pages_to_scrape)
        self.sector_context_arg = sector_context # Passed from orchestrator
        self.stock_name_arg = stock_name         # Passed from orchestrator
        
        try:
            self.start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else (datetime.now(timezone.utc).date() - timedelta(days=7))
            self.end_date_obj = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else datetime.now(timezone.utc).date()
        except ValueError:
            logger.error("Invalid date format. Please use YYYY-MM-DD. Using default 7-day range.")
            self.start_date_obj = datetime.now(timezone.utc).date() - timedelta(days=7)
            self.end_date_obj = datetime.now(timezone.utc).date()
        
        # Base URL for a relevant news section. This often needs manual identification.
        # Examples:
        # self.base_section_url = "https://www.moneycontrol.com/news/business/companies/"
        # self.base_section_url = "https://www.moneycontrol.com/news/business/markets/"
        # If a keyword is provided, try to use a tag page if moneycontrol supports it well,
        # otherwise, fall back to a general section and filter post-hoc.
        if self.target_keyword:
             # Moneycontrol search is often problematic for deep scraping. Tag pages might be better if available.
             # Example tag page format (this is hypothetical, verify actual format):
             # self.base_section_url = f"https://www.moneycontrol.com/news/tags/{self.target_keyword.replace(' ','-')}.html"
             # For now, let's stick to a general section and filter, as tag pages might not exist for all keywords.
             self.base_section_url = "https://www.moneycontrol.com/news/business/stocks/" # A common news section
        else:
            self.base_section_url = "https://www.moneycontrol.com/news/business/" # Broader if no keyword

        logger.info(f"MoneycontrolSpider initialized for: Keyword='{self.target_keyword}', Dates: {self.start_date_obj} to {self.end_date_obj}, Pages to try: {self.pages_to_scrape}, Base URL: {self.base_section_url}")

    def start_requests(self):
        # Moneycontrol uses "page-X" for pagination in many sections
        for i in range(1, self.pages_to_scrape + 1):
            if i == 1:
                url_to_scrape = self.base_section_url
            else:
                # Ensure base_section_url ends with a slash for proper joining
                base = self.base_section_url if self.base_section_url.endswith('/') else self.base_section_url + '/'
                url_to_scrape = f"{base}page-{i}/"
            
            logger.info(f"Requesting list page {i}: {url_to_scrape}")
            yield scrapy.Request(
                url_to_scrape,
                meta={
                    "playwright": True,
                    "playwright_page_methods": [
                        # Wait for a known container of news list items. VERIFY THIS SELECTOR.
                        PageMethod("wait_for_selector", "ul#newslist, ul.article_list, div.MyContBigListing", timeout=45000),
                        PageMethod("wait_for_timeout", 3000), # Extra wait for JS to settle
                        PageMethod("evaluate", "window.scrollBy(0, document.body.scrollHeight * 0.3)"), # Scroll a bit
                        PageMethod("wait_for_timeout", 1500),
                        PageMethod("evaluate", "window.scrollBy(0, document.body.scrollHeight * 0.6)"), # Scroll more
                        PageMethod("wait_for_timeout", 1500),
                    ],
                    "current_page_num": i
                },
                callback=self.parse_list_page,
                errback=self.handle_error
            )

    def handle_error(self, failure):
        logger.error(f"Request failed: {failure.request.url}, Reason: {failure.value}")
        # You can add more sophisticated error handling here if needed

    def parse_list_page(self, response):
        page_num = response.meta.get("current_page_num", 1)
        logger.info(f"Parsing list page {page_num}: {response.url}")

        # These selectors are EXAMPLES and MUST BE VERIFIED AND ADJUSTED for Moneycontrol
        # Option 1: Common list structure
        articles_css = response.css("ul#newslist > li, ul.article_list > li, div.MyContBigListing > ul > li")
        if not articles_css:
             # Option 2: Another common structure for news listings
            articles_css = response.css("div.nws_listing li, div.list--item") 
        
        if not articles_css:
            logger.warning(f"No articles found with primary selectors on {response.url}. HTML snapshot: mc_debug_list_page{page_num}.html")
            with open(f"mc_debug_list_page{page_num}.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            return

        logger.info(f"Found {len(articles_css)} potential article elements on page {page_num}.")
        articles_in_date_range_on_this_page = 0

        for article_el in articles_css:
            # Selectors for title and URL within each list item (VERIFY THESE)
            title = article_el.css("h2 a::text, strong a::text, div.FL a::attr(title)").get()
            relative_url = article_el.css("h2 a::attr(href), strong a::attr(href), div.FL a::attr(href)").get()
            
            # Date selector - Moneycontrol can be tricky, may need multiple attempts or more specific paths
            # Common patterns: <span class="date_class">...</span>, <p class="post-time">...</p>
            date_texts = article_el.css("p span::text, span.posted-on::text, div.datetime::text, span.date::text").getall()
            date_text_raw = " ".join(dt.strip() for dt in date_texts if dt.strip()) if date_texts else None

            if not title or not relative_url:
                # logger.debug("Skipping item: Missing title or relative_url in list.")
                continue
            
            article_url = urljoin(response.url, relative_url.strip())
            title_cleaned = title.strip()

            article_date_obj = None
            if date_text_raw:
                try:
                    # Remove "IST" or other timezone info that dateutil might misinterpret without tzinfo
                    date_text_cleaned = re.sub(r'\s*IST\s*$', '', date_text_raw.strip(), flags=re.IGNORECASE)
                    date_text_cleaned = date_text_cleaned.replace("Updated: ", "").replace("Published: ", "")
                    # Try common formats first
                    common_formats = ["%B %d, %Y, %I:%M %p", "%b %d, %Y, %I:%M %p", "%B %d, %Y", "%b %d, %Y"]
                    for fmt in common_formats:
                        try:
                            article_date_obj = datetime.strptime(date_text_cleaned, fmt).date()
                            break
                        except ValueError:
                            continue
                    if not article_date_obj: # Fallback to dateutil parser
                        article_date_obj = dateutil_parser.parse(date_text_cleaned, fuzzy=True).date()
                except Exception as e_date:
                    logger.debug(f"Dateutil failed to parse '{date_text_raw}' for '{title_cleaned}': {e_date}")
            
            if not article_date_obj:
                logger.warning(f"Could not parse date for '{title_cleaned}' ({article_url}). Skipping strict date filter for this item.")
                # Decide: Scrape anyway or skip? For now, let's scrape and pipeline can filter if date is null
            
            # Keyword filtering (if a target_keyword was provided)
            if self.target_keyword and not (self.target_keyword in title_cleaned.lower() or self.target_keyword in article_url.lower()):
                # logger.debug(f"Skipping '{title_cleaned}': keyword '{self.target_keyword}' not found in title/URL.")
                continue

            # Date filtering
            if article_date_obj:
                if not (self.start_date_obj <= article_date_obj <= self.end_date_obj):
                    logger.debug(f"Skipping '{title_cleaned}' ({article_date_obj}): outside date range {self.start_date_obj}-{self.end_date_obj}.")
                    if article_date_obj < self.start_date_obj and page_num > 1: # Optimization: if results are chronological
                        logger.info(f"Article date {article_date_obj} is older than start date. Stopping pagination for this section.")
                        return # Stop processing this list page and further pagination for this section
                    continue 
                articles_in_date_range_on_this_page += 1
            
            # If all checks pass (or date couldn't be parsed but we proceed)
            logger.info(f"Yielding for full parse: '{title_cleaned}' - Date: {article_date_obj or 'Unknown'}")
            yield scrapy.Request(
                article_url,
                callback=self.parse_article_content,
                meta={
                    "playwright": True,
                    "playwright_page_methods": [
                        # Selector for main article content body (VERIFY THIS)
                        PageMethod("wait_for_selector", "div#contentdata, div.article_content, section.content-area", timeout=30000),
                        PageMethod("wait_for_timeout", 1000), # Small wait for any lazy-loaded images/ads
                    ],
                    "original_title": title_cleaned,
                    "publication_date_obj": article_date_obj # Pass datetime.date object
                },
                errback=self.handle_error
            )
        
        # Basic pagination based on number of pages to scrape - if not date limited.
        # More robust pagination would check for a "next" button and if articles_in_date_range_on_this_page > 0
        # This spider's start_requests already handles iterating `pages_to_scrape`.

    def parse_article_content(self, response):
        title = response.meta.get("original_title")
        pub_date_obj = response.meta.get("publication_date_obj") # This is a datetime.date object or None

        # Selectors for article body text (VERIFY THESE)
        content_selectors = [
            "div#contentdata p",                            # Common Moneycontrol main content
            "div.content_wrapper p",                        # Another common one
            "div.article_content_wrapper p",
            "section.content-area p",                       # General HTML5
            "article p"                                     # General HTML5
        ]
        article_text_parts = []
        for selector in content_selectors:
            parts = response.css(f"{selector} ::text").getall() # Get all text nodes, including within <span> etc.
            if parts:
                article_text_parts.extend(parts)
                # logger.debug(f"Extracted text parts with selector: {selector}")
        
        article_text = " ".join([part.strip() for part in article_text_parts if part.strip()])
        article_text = re.sub(r'\s{2,}', ' ', article_text).strip() # Consolidate multiple spaces

        if not article_text or len(article_text) < 100: # Arbitrary length check for meaningful content
            logger.warning(f"Extracted text seems too short or empty from {response.url}. Text: '{article_text[:100]}...'")
            # Optionally save page for debugging short/empty content
            # self._save_debug_page(response.text, response.meta.get("current_page_num", 0), prefix="SHORT_CONTENT")
            return

        item = NewsArticleItem()
        item['url'] = response.url
        item['headline'] = title
        item['article_text'] = article_text
        item['publication_date'] = pub_date_obj # datetime.date object or None
        item['download_date'] = datetime.now(timezone.utc) # datetime object
        item['source_domain'] = "moneycontrol.com"
        item['language'] = 'en'
        
        # Authors - Example (VERIFY SELECTOR)
        authors_list = response.css("div.author_cont span a::text, meta[name='author']::attr(content)").getall()
        item['authors'] = [a.strip() for a in authors_list if a.strip()] if authors_list else []

        # Keywords/Tags - Example (VERIFY SELECTOR)
        keywords_list = response.css("div.tags_first_line a::text, meta[name='keywords']::attr(content)").getall()
        if keywords_list and isinstance(keywords_list[0], str) and ',' in keywords_list[0] and len(keywords_list)==1 : # Handle comma-separated meta keywords
             item['keywords_extracted'] = [k.strip() for k in keywords_list[0].split(',') if k.strip()]
        else:
            item['keywords_extracted'] = [k.strip() for k in keywords_list if k.strip()] if keywords_list else []

        # Assign sector/stock based on the initially passed arguments for this spider run
        item['related_sector'] = self.sector_context_arg
        item['related_stock'] = self.stock_name_arg if self.stock_name_arg else self.target_keyword # Fallback if stock_name not explicitly passed

        logger.info(f"Successfully parsed article: {title[:60]}... from {response.url}")