# ~/CombinedNiftyNewsApp/utils/newsfetch_lib/news_please_handler.py
from urllib.parse import unquote
from newsplease import NewsPlease
from .helpers import clean_text, unicode # Note the leading dot
import logging 
logger = logging.getLogger(__name__) 

class NewsPleaseHandler:
    """Handle interactions with the NewsPlease library."""

    def __init__(self, url: str):
        self.url = url
        print(f"[NewsPleaseHandler DEBUG] Initializing with URL: {self.url}") 
        try:
            self._raw_news_please_object = NewsPlease.from_url(self.url, timeout=10)
            self.__news_please = self._raw_news_please_object 
            if self.__news_please:
                print(f"[NewsPleaseHandler DEBUG] NewsPlease.from_url successful for {self.url}") 
                print(f"[NewsPleaseHandler DEBUG] Raw maintext: {repr(self.__news_please.maintext)}") 
                print(f"[NewsPleaseHandler DEBUG] Raw title: {repr(self.__news_please.title)}") 
            else:
                print(f"[NewsPleaseHandler DEBUG] NewsPlease.from_url returned None directly for {self.url}") 
                self._raw_news_please_object = None 
        except Exception as e:
            print(f"[NewsPleaseHandler DEBUG] Exception during NewsPlease.from_url for {self.url}: {e}") 
            logger.exception(f"NewsPlease.from_url failed for {self.url}") 
            self.__news_please = None
            self._raw_news_please_object = None 

    # __safe_execute is not directly used by __init__ in this debug version,
    # but kept if other methods might use it.
    @staticmethod
    def __safe_execute(func):
        """Executes a function and returns None if it raises an exception."""
        try:
            return func()
        except Exception as e_safe: 
            print(f"[NewsPleaseHandler DEBUG - __safe_execute] Exception caught: {e_safe}") 
            logger.exception("Exception in __safe_execute") 
            return None

    def is_valid(self) -> bool:
        """Check if the NewsPlease instance is valid."""
        return self.__news_please is not None

    @property
    def authors(self) -> list:
        """Return authors from NewsPlease instance."""
        if not self.is_valid(): return []
        return self.__news_please.authors if self.__news_please.authors is not None else []


    @property
    def date_publish(self) -> str:
        """Return publication date from NewsPlease instance."""
        if self.is_valid() and self.__news_please.date_publish is not None:
            return str(self.__news_please.date_publish)
        return None

    @property
    def date_modify(self) -> str:
        """Return modification date from NewsPlease instance."""
        if self.is_valid() and self.__news_please.date_modify is not None:
            return str(self.__news_please.date_modify)
        return None

    @property
    def date_download(self) -> str:
        """Return download date from NewsPlease instance."""
        if self.is_valid() and self.__news_please.date_download is not None:
            return str(self.__news_please.date_download)
        return None

    @property
    def image_url(self) -> str:
        """Return image URL from NewsPlease instance."""
        return self.__news_please.image_url if self.is_valid() else None

    @property
    def filename(self) -> str:
        """Return filename from NewsPlease instance."""
        if self.is_valid() and self.__news_please.filename:
            return unquote(self.__news_please.filename)
        return None

    @property
    def title_page(self) -> str:
        """Return title page from NewsPlease instance."""
        return self.__news_please.title_page if self.is_valid() else None

    @property
    def title_rss(self) -> str:
        """Return RSS title from NewsPlease instance."""
        return self.__news_please.title_rss if self.is_valid() else None

    @property
    def language(self) -> str:
        """Return language from NewsPlease instance."""
        return self.__news_please.language if self.is_valid() else None

    @property
    def summary(self) -> str: 
        """Return description from NewsPlease instance."""
        return self.__news_please.description if self.is_valid() else None

    @property
    def article(self) -> str:
        """Return cleaned article text from the NewsPlease instance."""
        if not self.is_valid():
            print("[NewsPleaseHandler DEBUG] article property: self.__news_please is invalid (None), returning None for article.") 
            return None
        if self.__news_please.maintext is None:
            print(f"[NewsPleaseHandler DEBUG] article property: self.__news_please.maintext is None for {self.url}, returning None for article.") 
            return None 
        return unicode(clean_text(self.__news_please.maintext))

    @property
    def source_domain(self) -> str:
        """Return source domain from NewsPlease instance."""
        return self.__news_please.source_domain if self.is_valid() else None

    @property
    def headline(self) -> str:
        """Return headline from NewsPlease instance."""
        if not self.is_valid(): return None
        if self.__news_please.title is None:
            print(f"[NewsPleaseHandler DEBUG] headline property: self.__news_please.title is None for {self.url}, returning None for headline.") 
            return None
        return unicode(self.__news_please.title)