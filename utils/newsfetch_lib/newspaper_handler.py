from newspaper import Article # This should now be newspaper4k's Article

from .helpers import clean_text, extract_keywords, summarize_article, unicode # Note the leading dot
import logging # Add this
logger = logging.getLogger(__name__) # Add this

class ArticleHandler:
    """Handle interactions with the Article class (from newspaper4k)."""

    def __init__(self, url: str):
        self.url = url
        print(f"[ArticleHandler DEBUG] Initializing with URL: {self.url}") # DEBUG
        self.__article = self.__initialize_article()
        if self.__article:
            print(f"[ArticleHandler DEBUG] Article object from newspaper4k initialized successfully for {self.url}.") # DEBUG
        else:
            print(f"[ArticleHandler DEBUG] Article object (newspaper4k) initialization FAILED for {self.url}.") # DEBUG

    def __initialize_article(self):
        """Initialize the Article instance."""
        # fetch_images=False and memoize_articles=False are good defaults for scraping efficiency
        return self.__safe_execute(lambda: Article(self.url, fetch_images=False, memoize_articles=False))

    @staticmethod
    def __safe_execute(func):
        """Executes a function and returns None if it raises an exception."""
        try:
            return func()
        except Exception as e:
            print(f"[ArticleHandler DEBUG - __safe_execute] Exception caught: {e}") # DEBUG
            logger.exception(f"Exception in ArticleHandler __safe_execute during function: {func}") # Log full traceback
            return None

    def is_valid(self):
        """Check if the Article instance is valid."""
        return self.__article is not None

    def download_and_parse(self):
        """Download and parse the article."""
        if self.is_valid():
            print(f"[ArticleHandler DEBUG] Downloading article (newspaper4k) for {self.url}") # DEBUG
            self.__safe_execute(self.__article.download) # Call download
            
            download_failed_due_to_exception = False
            if hasattr(self.__article, 'download_exception_msg') and self.__article.download_exception_msg: 
                print(f"[ArticleHandler DEBUG] Download (newspaper4k) FAILED for {self.url}. Exception: {self.__article.download_exception_msg}") # DEBUG
                download_failed_due_to_exception = True
            else:
                print(f"[ArticleHandler DEBUG] Download (newspaper4k) attempt made for {self.url}. Further status via parse.")

            # Attempt to parse if no immediate download exception was noted.
            # .parse() internally checks if download was successful enough to proceed.
            if not download_failed_due_to_exception:
                print(f"[ArticleHandler DEBUG] Parsing article (newspaper4k) for {self.url}") # DEBUG
                self.__safe_execute(self.__article.parse) # Call parse
                
                if self.__article.is_parsed: # Check the is_parsed flag
                    print(f"[ArticleHandler DEBUG] Parse (newspaper4k) completed (is_parsed is True).")
                    if not self.__article.text and not self.__article.title: # Check if it actually got content
                        print(f"[ArticleHandler DEBUG] Parse (newspaper4k) completed but yielded no text or title for {self.url}.")
                    else:
                        print(f"[ArticleHandler DEBUG] Parse (newspaper4k) seems to have yielded content for {self.url}.")
                else:
                    print(f"[ArticleHandler DEBUG] Parse (newspaper4k) FAILED or did not complete (is_parsed is False) for {self.url}.")
            else:
                print(f"[ArticleHandler DEBUG] Skipping parse (newspaper4k) because download reported an exception for {self.url}.")
        else:
            print(f"[ArticleHandler DEBUG] download_and_parse (newspaper4k) skipped: Article object is not valid for {self.url}.")

    @property
    def authors(self):
        """Return authors from the Article instance."""
        if not self.is_valid(): return []
        return self.__article.authors if self.__article.authors is not None else []

    @property
    def date_publish(self):
        """Return publication date from the Article instance."""
        if not self.is_valid(): return None
        if self.__article.publish_date:
            return str(self.__article.publish_date)
        return self.__article.meta_data.get("published_time")


    @property
    def keywords(self):
        """Return keywords from the Article instance."""
        if not self.is_valid():
            return []
        # For keywords, .nlp() must be called. Let's ensure it's called if needed.
        if not self.__article.keywords and self.__article.is_parsed: # Only run nlp if parsed and no keywords yet
            print(f"[ArticleHandler DEBUG] Keywords: Calling .nlp() for {self.url} as keywords are empty.") # DEBUG
            self.__safe_execute(self.__article.nlp)

        article_keywords = self.__article.keywords
        if article_keywords:
             processed_keywords = self.__process_keywords(article_keywords)
             print(f"[ArticleHandler DEBUG] Keywords from newspaper4k: {processed_keywords}") # DEBUG
             return processed_keywords
        
        print("[ArticleHandler DEBUG] newspaper4k keywords empty after nlp/check, falling back to custom extraction.") # DEBUG
        current_article_text = self.article 
        if current_article_text:
            return extract_keywords(current_article_text)
        return []


    @staticmethod
    def __process_keywords(keywords, max_keywords=None):
        """Process keywords to remove duplicates and limit the number."""
        unique_keywords = list(set(keywords))
        return unique_keywords[:max_keywords] if max_keywords is not None else unique_keywords

    @property
    def summary(self):
        """Return summary from the Article instance."""
        if not self.is_valid(): return None

        # For summary, .nlp() must be called.
        if not self.__article.summary and self.__article.is_parsed: # Only run nlp if parsed and no summary yet
            print(f"[ArticleHandler DEBUG] Summary: Calling .nlp() for {self.url} as summary is empty.") # DEBUG
            self.__safe_execute(self.__article.nlp)

        article_summary = self.__article.summary
        print(f"[ArticleHandler DEBUG] Raw summary from newspaper4k: {repr(article_summary[:200]) if article_summary else 'None'}") # DEBUG
        if article_summary: 
            return unicode(article_summary)
        
        print("[ArticleHandler DEBUG] newspaper4k summary empty after nlp/check, falling back to custom summarizer.") # DEBUG
        current_article_text = self.article 
        if current_article_text:
            return unicode(summarize_article(current_article_text))
        return "" 

    @property
    def article(self):
        """Return cleaned article text from the Article instance."""
        if not self.is_valid():
            print("[ArticleHandler DEBUG] article property: self.__article (newspaper4k) is invalid, returning None.") # DEBUG
            return None 
        
        # Ensure article has been parsed before trying to access .text
        if not self.__article.is_parsed:
            print("[ArticleHandler DEBUG] article property: Article not parsed yet, cannot get text. Returning None.") # DEBUG
            return None

        raw_text = self.__article.text
        print(f"[ArticleHandler DEBUG] article property: Raw text from newspaper4k (first 200 chars): {repr(raw_text[:200]) if raw_text else 'None'}") # DEBUG
        if not raw_text: 
            return None 
        return unicode(clean_text(raw_text))

    @property
    def publication(self):
        """Return publication name from the Article instance."""
        if not self.is_valid(): return None
        site_name = self.__article.meta_data.get("og", {}).get("site_name")
        if site_name: return site_name
        if self.__article.source_url:
            try:
                from urllib.parse import urlparse
                return urlparse(self.__article.source_url).netloc
            except:
                pass 
        return None

    @property
    def category(self):
        """Return category from the Article instance."""
        if not self.is_valid():
            return None
        meta_cat = (self.__article.meta_data.get("category") or
                    self.__article.meta_data.get("section") or
                    self.__article.meta_data.get("article", {}).get("section"))
        if meta_cat: return meta_cat
        return None

    @property
    def headline(self):
        """Return title from the Article instance."""
        if not self.is_valid() or not self.__article.title:
            print(f"[ArticleHandler DEBUG] headline property: newspaper4k title is missing or invalid.") #DEBUG
            return None
        # Ensure article has been parsed before trying to access .title
        if not self.__article.is_parsed and self.__article.title is None: # check if title is None AND not parsed
             print("[ArticleHandler DEBUG] headline property: Article not parsed yet and title is None. Returning None.") # DEBUG
             return None
        return unicode(self.__article.title)

    @property
    def meta_favicon(self):
        """Return meta favicon from the Article instance."""
        if not self.is_valid(): return None
        return self.__article.meta_favicon