# ~/CombinedNiftyNewsApp/scrape_financial_news_db.py
import asyncio
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import twisted.internet.asyncioreactor
twisted.internet.asyncioreactor.install()
import os
import logging
from datetime import datetime, timedelta, timezone
from twisted.internet import reactor, defer
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings
from scrapy.utils.log import configure_logging as scrapy_configure_logging

# Ensure main project utils are discoverable if Scrapy project is nested
import sys
project_root_for_utils = os.path.abspath(os.path.join(os.path.dirname(__file__), '.')) # Assumes this script is in project root
if project_root_for_utils not in sys.path:
    sys.path.insert(0, project_root_for_utils)

from utils.gemini_utils import NIFTY_SECTORS_QUERY_CONFIG
from utils.database_models import create_db_and_tables # To ensure tables exist

# --- Configuration ---
# Map domains to your spider names (must match spider's `name` attribute)
DOMAIN_TO_SPIDER_MAP = {
    "moneycontrol.com": "moneycontrol", # Example, if you create this spider
    # "economictimes.indiatimes.com": "economictimes", # Add more as you create them
    # "livemint.com": "livemint_spider_name",
}
# Domains not in this map could fall back to GoogleSearchNewsURLExtractor or be skipped.

OUTPUT_DIR_LOGS = "scraper_run_logs_and_processed_urls" # Keep your log dir
os.makedirs(OUTPUT_DIR_LOGS, exist_ok=True)

# Configure Scrapy's logging to go to a specific file and also allow project's logger
scrapy_configure_logging({
    'LOG_FILE': os.path.join(OUTPUT_DIR_LOGS, 'scrapy_bulk_scrape.log'),
    'LOG_LEVEL': 'INFO', # Or DEBUG for more Scrapy details
    'LOG_FORMAT': '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
})

# Configure your script's logger
logger = logging.getLogger("BulkNewsScraperOrchestrator")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(os.path.join(OUTPUT_DIR_LOGS, "bulk_orchestrator.log"))
stream_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)


def generate_targets_from_config(config):
    """
    Generates a list of targets (keywords, associated sectors/stocks)
    Each item: {'keyword': str, 'sector_context': str, 'stock_name': str or None}
    """
    targets = []
    for sector_name, sector_details in config.items():
        # Sector-level general keywords (take a few representative ones)
        sector_base_keywords = sector_details.get("newsapi_keywords", [])
        for skw in sector_base_keywords[:2]: # Example: Use top 2 general keywords for the sector
            targets.append({'keyword': skw, 'sector_context': sector_name, 'stock_name': None})
        targets.append({'keyword': sector_name, 'sector_context': sector_name, 'stock_name': None}) # Sector name itself

        # Stock-level keywords
        if "stocks" in sector_details:
            for stock_ticker, stock_keywords_list in sector_details["stocks"].items():
                # Use stock ticker/name as a primary keyword
                targets.append({'keyword': stock_ticker, 'sector_context': sector_name, 'stock_name': stock_ticker})
                # Optionally, add one or two very specific keywords for that stock
                # for sskw in stock_keywords_list[:1]:
                #     targets.append({'keyword': f"{stock_ticker} {sskw}", 'sector_context': sector_name, 'stock_name': stock_ticker})
    
    # Deduplicate targets based on the keyword itself to avoid redundant scraping runs for the same search term
    unique_targets_by_keyword = {t['keyword'].lower(): t for t in targets}
    return list(unique_targets_by_keyword.values())


@defer.inlineCallbacks
def crawl(runner, targets, start_date_str, end_date_str, domains_to_scrape):
    for target_info in targets:
        keyword = target_info['keyword']
        # sector_context = target_info['sector_context'] # Pass these to spider if needed for item population
        # stock_name = target_info['stock_name']

        for domain in domains_to_scrape:
            spider_name = DOMAIN_TO_SPIDER_MAP.get(domain)
            if spider_name:
                logger.info(f"Starting Scrapy crawl for: Keyword='{keyword}', Domain='{domain}', Spider='{spider_name}'")
                # Pass parameters to the spider via -a option in command line, or kwargs here
                yield runner.crawl(spider_name, 
                                   target_keyword=keyword, 
                                   start_date_str=start_date_str, 
                                   end_date_str=end_date_str,
                                   pages_to_scrape=2) # Configure pages per domain/keyword
                logger.info(f"Finished Scrapy crawl for: Keyword='{keyword}', Domain='{domain}'")
                time.sleep(random.uniform(5,10)) # Politeness delay between different spider runs/domains
            else:
                logger.warning(f"No Scrapy spider configured for domain: {domain}. Skipping for keyword '{keyword}'.")
    reactor.stop()


def run_all_spiders(targets, start_date_str, end_date_str, domains_to_scrape):
    # Need to change directory into the Scrapy project for get_project_settings to work correctly
    # Store original cwd and restore it later
    original_cwd = os.getcwd()
    scrapy_project_path = os.path.join(original_cwd, "news_scrapers") # Path to your Scrapy project
    
    if not os.path.exists(os.path.join(scrapy_project_path, "scrapy.cfg")):
        logger.error(f"Scrapy project not found at {scrapy_project_path}. Make sure you ran 'scrapy startproject news_scrapers' in CombinedNiftyNewsApp.")
        return
        
    os.chdir(scrapy_project_path)
    
    try:
        settings = get_project_settings()
        # settings.set('LOG_LEVEL', 'DEBUG') # Override log level if needed for spiders
        runner = CrawlerRunner(settings)
        crawl(runner, targets, start_date_str, end_date_str, domains_to_scrape)
        reactor.run() # Process will block here until all crawls are finished
    except Exception as e:
        logger.error(f"Error running Scrapy spiders: {e}", exc_info=True)
    finally:
        os.chdir(original_cwd) # Restore original working directory
        logger.info("All Scrapy crawling tasks complete or reactor stopped.")


if __name__ == "__main__":
    logger.info(f"--- Starting Bulk News Scraping Orchestrator (Scrapy-based) ---")
    create_db_and_tables() # Ensure DB schema exists

    try:
        start_date_input_str = input(f"Enter START date for article publication (YYYY-MM-DD): ").strip()
        end_date_input_str = input(f"Enter END date for article publication (YYYY-MM-DD): ").strip()
        
        scrape_start_date_obj = datetime.strptime(start_date_input_str, "%Y-%m-%d").date()
        scrape_end_date_obj = datetime.strptime(end_date_input_str, "%Y-%m-%d").date()

        if scrape_start_date_obj > scrape_end_date_obj:
            print("Start date cannot be after end date. Exiting.")
            exit()
        
        logger.info(f"Targeting articles published between: {scrape_start_date_obj} and {scrape_end_date_obj}")
        
        # Only scrape domains for which spiders are defined in DOMAIN_TO_SPIDER_MAP
        domains_with_spiders = list(DOMAIN_TO_SPIDER_MAP.keys())
        if not domains_with_spiders:
            logger.error("No domains configured with spiders in DOMAIN_TO_SPIDER_MAP. Exiting.")
            exit()
            
        logger.info(f"Will attempt to scrape for domains: {', '.join(domains_with_spiders)}")

        scraping_targets = generate_targets_from_config(NIFTY_SECTORS_QUERY_CONFIG)
        logger.info(f"Generated {len(scraping_targets)} unique keyword targets to process across configured domains.")

        run_all_spiders(scraping_targets, start_date_input_str, end_date_input_str, domains_with_spiders)

    except ValueError:
        logger.error("Invalid date format. Please use YYYY-MM-DD. Exiting.")
    except KeyboardInterrupt:
        logger.info("\n--- Scraping interrupted by user (Ctrl+C) ---")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the main orchestrator: {e}", exc_info=True)
    finally:
        logger.info(f"--- Bulk News Scraping Orchestrator Finished ---")