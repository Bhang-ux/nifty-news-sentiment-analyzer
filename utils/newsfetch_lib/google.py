# ~/CombinedNiftyNewsApp/utils/newsfetch_lib/google.py
import logging
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import time
import urllib.parse
import os
import random
from fake_useragent import UserAgent # Ensure this is installed: pip install fake-useragent

logger = logging.getLogger("utils.newsfetch_lib.google") # Consistent logger name

class GoogleSearchNewsURLExtractor:
    BASE_URL = "https://www.google.com/search"
    REFINED_LINK_XPATHS = [
        "//div[contains(@class,'MjjYud')]//a[@jsname='UWckNb'][@href]",             # Modern organic results
        "//div[contains(@class,'Gx5Zad')]//a[@href]",                               # "Top stories" / news carousels
        "//div[@id='search']//div[contains(@class,'g ')]//div[@class='yuRUbf']/a[@href]", # Older common title link
        "//div[@id='rso']//div[contains(@class,'MjjYud')]//div[not(contains(@style,'display:none'))]//a[@href][.//h3]", # Visible links with H3
        "//div[@id='search']//div[contains(@class,'g ')]//div[contains(@class,'VwiC3b')]//a[@href]", # Another older structure
    ]
    BROADER_LINK_XPATH = "//div[@id='search']//a[@href][.//h3]" # Fallback: any link containing an H3 within search results
    RESULTS_CONTAINER_ID = "rcnt" # Results container might change, 'search' is also common
    RESULTS_ELEMENTS_XPATH = "//div[@id='search']//div[contains(@class, 'g') or contains(@class, 'MjjYud') or contains(@class, 'Gx5Zad')]"
    CAPTCHA_DIR = "google_captcha_pages"

    def __init__(self, keyword, news_domain, start_date_str=None, end_date_str=None, lang="en", country_code="IN", num_pages=1, driver_options=None, proxy_config=None):
        self.keyword = keyword
        self.news_domain = news_domain.lower()
        self.start_date_str = start_date_str # Expected format: MM/DD/YYYY
        self.end_date_str = end_date_str   # Expected format: MM/DD/YYYY
        self.lang = lang
        self.country_code = country_code
        self.num_pages_to_scrape = max(1, num_pages)
        self.driver_options_custom = driver_options
        self.proxy_config = proxy_config # Dict for proxy, e.g., {'http': 'http://user:pass@host:port'}
        self.driver = None
        self.urls = []
        try:
            self.ua_rotator = UserAgent(browsers=['chrome', 'edge'], fallback='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36') # More recent fallback
        except Exception as e_ua_init:
            logger.warning(f"[GoogleSearch] UserAgent initialization failed: {e_ua_init}. Using a fixed UA.")
            self.ua_rotator = None

        os.makedirs(self.CAPTCHA_DIR, exist_ok=True)
        logger.info(f"[GoogleSearch] Init - Keyword: '{self.keyword}', Domain: '{self.news_domain}', Dates: {self.start_date_str}-{self.end_date_str}, Pages: {self.num_pages_to_scrape}")

    def _get_or_create_driver(self):
        if self.driver:
            try:
                self.driver.current_url # Check if responsive
                return self.driver
            except WebDriverException:
                logger.warning("[GoogleSearch] Existing driver unresponsive. Creating new one.")
                try: self.driver.quit()
                except: pass
                self.driver = None

        if self.ua_rotator:
            try:
                user_agent_to_use = self.ua_rotator.random
            except Exception as e_ua_random:
                logger.warning(f"[GoogleSearch] ua_rotator.random failed: {e_ua_random}. Using hardcoded fallback UA.")
                user_agent_to_use = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
        else:
            user_agent_to_use = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"

        options = uc.ChromeOptions()

        if self.driver_options_custom:
            for opt_arg in self.driver_options_custom:
                options.add_argument(opt_arg)
        
        options.add_argument(f'--user-agent={user_agent_to_use}')
        # Default to headless if not explicitly set otherwise by driver_options_custom
        if not any('--headless' in opt.lower() for opt in (self.driver_options_custom or [])) and \
           not any('headless=false' in opt.lower() for opt in (self.driver_options_custom or [])):
            options.add_argument('--headless=new')
            
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu') # Often needed for headless
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--window-size=1920,1080')
        options.add_argument("--start-maximized") # Can help appear more human
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-logging") # Chrome's own verbose logging
        options.add_argument("--log-level=3")    # Only fatal errors from Chrome
        options.add_argument(f"--lang={self.lang},{self.lang.split('-')[0]};q=0.9") # e.g. en-US,en;q=0.9
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--allow-running-insecure-content')
        
        # Removed problematic experimental options, relying on UC's patching
        # options.add_experimental_option("excludeSwitches", ["enable-automation"])
        # options.add_experimental_option('useAutomationExtension', False)

        # Proxy configuration for uc.Chrome (basic, non-authenticated or using selenium-wire for auth)
        seleniumwire_options = None
        if self.proxy_config:
            if self.proxy_config.get('seleniumwire_options'): # If full selenium-wire options provided
                seleniumwire_options = self.proxy_config['seleniumwire_options']
                logger.info(f"[GoogleSearch] Using selenium-wire with provided options.")
            elif self.proxy_config.get('http'): # Basic proxy for Chrome arg
                proxy_server_arg = self.proxy_config['http'].replace('http://', '').replace('https://', '')
                options.add_argument(f"--proxy-server={proxy_server_arg}")
                logger.info(f"[GoogleSearch] Attempting to use direct proxy via Chrome arg: {proxy_server_arg}")
        
        try:
            logger.info(f"[GoogleSearch] Initializing UC instance with UA: {user_agent_to_use}")
            if seleniumwire_options:
                from seleniumwire.undetected_chromedriver import Chrome as uc_Chrome_sw # Import only if needed
                self.driver = uc_Chrome_sw(options=options, seleniumwire_options=seleniumwire_options, use_subprocess=True)
            else:
                self.driver = uc.Chrome(options=options, use_subprocess=True)
        except Exception as e:
            logger.error(f"[GoogleSearch] Failed to initialize undetected_chromedriver: {e}", exc_info=True)
            self.driver = None
            raise # Re-raise to allow caller to handle
        return self.driver

    def _construct_search_url(self, page_num=0):
        query_parts = [f"\"{self.keyword}\"", f"site:{self.news_domain}"] # Use quotes for more exact keyword match
        search_term_for_q = " ".join(query_parts)
        params = {'q': search_term_for_q, 'hl': self.lang, 'gl': self.country_code, 'lr': f"lang_{self.lang}"}
        tbs_parts = ["cdr:1"]
        if self.start_date_str: tbs_parts.append(f"cd_min:{self.start_date_str}")
        if self.end_date_str: tbs_parts.append(f"cd_max:{self.end_date_str}")
        params['tbs'] = ",".join(tbs_parts)
        if page_num > 0: params['start'] = page_num * 10
        # params['filter'] = '0' # Try to disable duplicate filtering by Google, might not always work
        return f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"

    def _is_captcha_page(self, current_url, page_source):
        page_source_lower = page_source.lower() if page_source else ""
        current_url_lower = current_url.lower() if current_url else ""
        
        captcha_url_indicators = ["google.com/sorry/", "ipv4.google.com/sorry/"]
        captcha_text_indicators = [
            "unusual traffic from your computer network", "recaptcha",
            "our systems have detected unusual traffic", "www.google.com/recaptcha",
            "ដើម្បីបន្ត", "voor je verdergaat naar google", "antes de continuar" # Examples for other languages
        ]
        consent_text_indicators = ["before you continue to google", "consent.google.com/ml?continue="]

        if any(indicator in current_url_lower for indicator in captcha_url_indicators) or \
           any(indicator in page_source_lower for indicator in captcha_text_indicators):
            return True
        # If it's a consent page, it's not strictly a CAPTCHA but needs handling or might lead to one
        if any(indicator in current_url_lower for indicator in consent_text_indicators) or \
           any(indicator in page_source_lower for indicator in consent_text_indicators):
            logger.warning("[GoogleSearch] Consent-like page detected.")
            # We treat consent pages as something to get past, not a hard CAPTCHA block initially.
            # The _handle_consent_popups should deal with it. If it fails, then it might become a block.
            return False # Let consent handler try first
        return False

    def _save_debug_page(self, page_source, page_num_attempted, prefix="DEBUG_PAGE"):
        try:
            sanitized_keyword = "".join(c if c.isalnum() else "_" for c in self.keyword[:25])
            sanitized_domain = self.news_domain.replace('/', '_').replace(':', '').replace('.', '_')
            filename_ts = int(time.time())
            filename = os.path.join(self.CAPTCHA_DIR, f"{prefix}_{sanitized_keyword}_{sanitized_domain}_p{page_num_attempted}_{filename_ts}.html")
            with open(filename, "w", encoding="utf-8") as f: f.write(page_source)
            logger.info(f"[GoogleSearch] Saved debug page source: {filename}")
        except Exception as e:
            logger.error(f"[GoogleSearch] Error saving debug page: {e}")

    def _extract_links_from_page(self):
        extracted_page_urls = []
        for xpath_idx, xpath_query in enumerate(self.REFINED_LINK_XPATHS):
            try:
                WebDriverWait(self.driver, 4).until(EC.presence_of_all_elements_located((By.XPATH, xpath_query)))
                link_elements = self.driver.find_elements(By.XPATH, xpath_query)
                if link_elements:
                    current_xpath_urls = []
                    for link_element in link_elements:
                        href = link_element.get_attribute("href")
                        if href and self._is_valid_url(href):
                            current_xpath_urls.append(href)
                    if current_xpath_urls:
                        logger.info(f"[GoogleSearch] XPath #{xpath_idx+1} ('{xpath_query[:50]}...') yielded {len(current_xpath_urls)} valid URLs.")
                        return list(dict.fromkeys(current_xpath_urls)) 
            except TimeoutException:
                logger.debug(f"[GoogleSearch] XPath #{xpath_idx+1} ('{xpath_query[:50]}...') timed out/no elements.")
            except Exception as e_xpath:
                logger.warning(f"[GoogleSearch] Error with XPath #{xpath_idx+1} ('{xpath_query[:50]}...'): {e_xpath}")
        
        logger.warning("[GoogleSearch] Refined XPaths yielded no valid URLs. Trying broader XPath.")
        try:
            link_elements = self.driver.find_elements(By.XPATH, self.BROADER_LINK_XPATH)
            for link_element in link_elements:
                href = link_element.get_attribute("href")
                if href and self._is_valid_url(href): extracted_page_urls.append(href)
            if extracted_page_urls: logger.info(f"[GoogleSearch] Broader XPath found {len(extracted_page_urls)} valid URLs.")
        except Exception as e_broad_xpath:
            logger.error(f"[GoogleSearch] Error with broader XPath: {e_broad_xpath}")
        return list(dict.fromkeys(extracted_page_urls))

    def _is_valid_url(self, url_str):
        try:
            parsed_url = urllib.parse.urlparse(url_str)
            if parsed_url.scheme not in ['http', 'https']: return False
            netloc_lower = parsed_url.netloc.lower()
            
            google_domains_to_skip = ['google.com', 'google.co.in', 'accounts.google.com', 
                                      'support.google.com', 'maps.google.com', 'policies.google.com', 
                                      'play.google.com', 'photos.google.com', 'drive.google.com', 
                                      'news.google.com', 'translate.google.com', 'images.google.com',
                                      'google.org', 'googleblog.com']
            if any(gdomain in netloc_lower for gdomain in google_domains_to_skip):
                if "/url?q=" in url_str:
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    actual_target_urls = query_params.get('q')
                    if actual_target_urls and actual_target_urls[0]:
                        target_netloc = urllib.parse.urlparse(actual_target_urls[0]).netloc.lower()
                        if self.news_domain in target_netloc: return True
                return False

            if self.news_domain in netloc_lower:
                common_non_article_patterns = [
                    '.pdf', '.xml', '.zip', '.jpg', '.png', '.gif', '.webp', 'mailto:', 'javascript:', 
                    '.mp3', '.mp4', '.xls', '.xlsx', '.doc', '.docx', '.ppt', '.pptx', '#', 
                    '?replytocom=','/feed/', '/rss/', '/author/', '/category/', '/tag/', '/wp-content/',
                    '/about-us', '/contact', '/privacy', '/terms', '/sitemap', '/advertise'
                ]
                url_lower = url_str.lower()
                if not any(pattern in url_lower for pattern in common_non_article_patterns):
                    # Check for a reasonable path length suggesting an article page
                    path_parts = [part for part in parsed_url.path.split('/') if part]
                    if len(path_parts) >= 1 and len(path_parts[-1]) > 5: # e.g., /story-name.html or /section/story-name
                        return True
        except Exception as e_val:
            logger.debug(f"[GoogleSearch] URL validation error for '{url_str}': {e_val}")
        return False

    def _handle_consent_popups(self):
        consent_selectors = [ # Order by likelihood or commonality
            (By.ID, "L2AGLb"), # Often the main "Accept all" button ID
            (By.XPATH, "//button[.//div[contains(translate(text(), 'ACCEPPT', 'accept'), 'accept all')]]"),
            (By.XPATH, "//button[contains(translate(@aria-label, 'ACCEPPT', 'accept'), 'accept all')]"),
            (By.XPATH, "//div[contains(text(), 'Before you continue')]/ancestor::div[1]//button[.//span[contains(translate(text(),'AGREE','agree'),'agree') or contains(translate(text(),'ACCEPT','accept'),'accept')]]"),
            (By.XPATH, "//button[contains(translate(., 'ACCEPPT', 'accept'), 'accept all')]"), # Check button text itself
            (By.XPATH, "//button[contains(translate(., 'AGREE', 'agree'), 'agree to all')]"),
            (By.XPATH, "//button[.//span[contains(translate(., 'ACCEPPT', 'accept'), 'accept all')]]"),
        ]
        for by_type, selector in consent_selectors:
            try:
                # Short wait for each specific selector
                consent_button = WebDriverWait(self.driver, 2.5).until(EC.element_to_be_clickable((by_type, selector)))
                logger.info(f"[GoogleSearch] Consent popup/button detected via '{selector}'. Attempting to click.")
                self.driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", consent_button)
                time.sleep(random.uniform(2.0, 3.5)) # Wait for potential page reload/overlay dismissal
                logger.info("[GoogleSearch] Clicked consent button.")
                return True # Consent handled
            except TimeoutException:
                logger.debug(f"[GoogleSearch] Consent selector '{selector}' not found or not clickable in time.")
            except Exception as e_consent:
                logger.warning(f"[GoogleSearch] Error interacting with consent button ('{selector}'): {e_consent}")
        logger.info("[GoogleSearch] No obvious consent popups found or handled with current selectors.")
        return False

    def fetch_all_urls(self):
        self.urls = []
        driver = None 
        try:
            driver = self._get_or_create_driver()
            if not driver: return []

            all_urls_from_pages_session = []
            for page_idx in range(self.num_pages_to_scrape):
                current_search_url = self._construct_search_url(page_num=page_idx)
                logger.info(f"[GoogleSearch] Navigating to page {page_idx + 1}/{self.num_pages_to_scrape}: {current_search_url}")
                
                try:
                    driver.get(current_search_url)
                    # Initial implicit wait is handled by get, add small explicit for dynamic content
                    time.sleep(random.uniform(2.0, 4.0)) 
                    
                    self._handle_consent_popups() # Attempt to clear consent dialogs
                    # Add another small sleep in case consent click reloads or changes DOM significantly
                    time.sleep(random.uniform(2.5, 4.0)) 

                    # Check for CAPTCHA after navigation and consent handling attempts
                    current_page_source = driver.page_source
                    if self._is_captcha_page(driver.current_url, current_page_source):
                        self._save_debug_page(current_page_source, page_idx + 1, prefix="CAPTCHA_ENCOUNTERED")
                        logger.error(f"[GoogleSearch] CAPTCHA or block page detected on page {page_idx + 1} for '{self.keyword}'. Aborting this Google query.")
                        break 

                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, self.RESULTS_ELEMENTS_XPATH)))
                    logger.debug(f"[GoogleSearch] Page {page_idx + 1} results area presumed present.")
                    
                    driver.execute_script(f"window.scrollBy(0, {random.randint(300, 600)});") # Slightly more scroll
                    time.sleep(random.uniform(1.5, 3.0))

                    page_specific_urls = self._extract_links_from_page()
                    logger.info(f"[GoogleSearch] Extracted {len(page_specific_urls)} relevant links on page {page_idx + 1}.")
                    all_urls_from_pages_session.extend(page_specific_urls)

                    if not page_specific_urls and page_idx == 0:
                        logger.warning(f"[GoogleSearch] No relevant links on first page for '{self.keyword}'. Saving page for review.")
                        self._save_debug_page(current_page_source, page_idx + 1, prefix="NO_LINKS_FOUND_P1")
                        break 
                    
                    if page_idx < self.num_pages_to_scrape - 1 and page_specific_urls:
                        time.sleep(random.uniform(6, 10)) # Randomized delay between successful SERPs
                    elif not page_specific_urls: # If no links on current page, don't try next for this query
                        logger.info(f"[GoogleSearch] No links found on page {page_idx+1}, stopping for this query.")
                        break

                except TimeoutException:
                    logger.warning(f"[GoogleSearch] Timeout waiting for results on page {page_idx + 1}. URL: {driver.current_url if driver else 'N/A'}, Title: {driver.title[:100] if driver and driver.title else 'N/A'}")
                    if driver and self._is_captcha_page(driver.current_url, driver.page_source):
                        self._save_debug_page(driver.page_source, page_idx + 1, prefix="CAPTCHA_ON_TIMEOUT")
                    break 
                except WebDriverException as wde_page:
                    logger.error(f"[GoogleSearch] WebDriverException on page {page_idx + 1}: {wde_page}", exc_info=False)
                    if driver and self._is_captcha_page(driver.current_url, driver.page_source):
                        self._save_debug_page(driver.page_source, page_idx + 1, prefix="CAPTCHA_ON_WEBDRIVER_EXC")
                    break 
                except Exception as e_page:
                    logger.error(f"[GoogleSearch] Unexpected error processing page {page_idx + 1}: {e_page}", exc_info=True)
                    if driver and self._is_captcha_page(driver.current_url, driver.page_source):
                        self._save_debug_page(driver.page_source, page_idx + 1, prefix="CAPTCHA_ON_UNEXPECTED_EXC")
                    break 
            
            self.urls = sorted(list(dict.fromkeys(all_urls_from_pages_session)))
            logger.info(f"[GoogleSearch] Finished fetch operation. Total unique URLs for '{self.keyword} site:{self.news_domain}': {len(self.urls)}")
            return self.urls

        except WebDriverException as wde_global:
            logger.error(f"[GoogleSearch] Critical WebDriverException (e.g., init or major navigation): {wde_global}", exc_info=True)
            return []
        except Exception as e_global:
            logger.error(f"[GoogleSearch] Global unexpected error in operation: {e_global}", exc_info=True)
            return []
        finally:
            self.close_driver()

    def close_driver(self):
        if self.driver:
            try:
                logger.info("[GoogleSearch] Attempting to quit Selenium driver.")
                self.driver.quit()
            except Exception as e: logger.error(f"[GoogleSearch] Error occurred while quitting Selenium driver: {e}")
            finally: self.driver = None; logger.debug("[GoogleSearch] Driver instance explicitly set to None after quit attempt.")

# Standalone Test Block
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    
    # --- Test Parameters ---
    test_parameters = [
        {"keyword": "Infosys Q1 results analysis", "domain": "moneycontrol.com", "start": "04/01/2024", "end": "07/25/2024"},
        {"keyword": "Tata Motors EV sales", "domain": "autocarindia.com", "start": "05/01/2024", "end": "06/30/2024"},
        {"keyword": "Nifty Bank outlook next week", "domain": "livemint.com", "start": "06/15/2024", "end": "06/25/2024"},
    ]
    
    selected_test = test_parameters[0] # Change index to test different parameters

    logger.info(f"--- Starting Standalone Test for GoogleSearchNewsURLExtractor ---")
    logger.info(f"Testing with: Keyword='{selected_test['keyword']}', Domain='{selected_test['domain']}'")

    # To test headful (visible browser), pass driver_options that DON'T include headless
    # test_driver_options = ['--window-size=1920,1080'] # Example for headful
    test_driver_options = None # Let _get_or_create_driver use its defaults (which includes headless=new)

    extractor = GoogleSearchNewsURLExtractor(
        keyword=selected_test["keyword"],
        news_domain=selected_test["domain"],
        start_date_str=selected_test["start"],
        end_date_str=selected_test["end"],
        num_pages=1, # Keep to 1 for testing to reduce requests
        driver_options=test_driver_options
    )
    
    found_urls_test = []
    try:
        found_urls_test = extractor.fetch_all_urls() 
        if found_urls_test:
            logger.info(f"\n--- Successfully fetched {len(found_urls_test)} URLs for '{selected_test['keyword']}': ---")
            for i, url_item in enumerate(found_urls_test[:20]): # Print up to 20
                logger.info(f"{i+1}. {url_item}")
        else:
            logger.warning(f"--- No URLs found for '{selected_test['keyword']}' in the standalone test. ---")
            logger.warning("Check 'google_captcha_pages/' directory for any saved CAPTCHA/block/debug HTML pages.")
            
    except Exception as e_test_main:
        logger.error(f"An error occurred during the standalone test execution: {e_test_main}", exc_info=True)
    
    logger.info(f"--- GoogleSearchNewsURLExtractor standalone test finished. ---")