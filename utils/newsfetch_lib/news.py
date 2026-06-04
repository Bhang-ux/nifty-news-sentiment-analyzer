# ~/CombinedNiftyNewsApp/utils/newsfetch_lib/news.py
from .newspaper_handler import ArticleHandler 
from .news_please_handler import NewsPleaseHandler 
from .soup_handler import SoupHandler 
# Removed logging import as it's not used directly in this class, debugs use print

class Newspaper: # Make sure this line is exactly like this
    """Class to scrape and extract information from a news article."""

    def __init__(self, url: str) -> None:
        """Initialize the Newspaper object with the given URL."""
        print(f"[Newspaper DEBUG __init__] Initializing for URL: {url}") 
        self.url = url
        self.__news_please = NewsPleaseHandler(url) 
        self.__article = ArticleHandler(url)       
        self.__soup = SoupHandler(url)             

        self.__validate_initialization() 

        if self.__article.is_valid():
            print("[Newspaper DEBUG __init__] ArticleHandler (newspaper4k) is_valid, calling download_and_parse.") 
            self.__article.download_and_parse() 
        else:
            print("[Newspaper DEBUG __init__] ArticleHandler (newspaper4k) is NOT valid after initialization.") 

        self.headline = self.__extract_headline()
        self.article = self.__extract_article() 
        self.authors = self.__extract_authors()
        self.date_publish = self.__extract_date_publish()
        self.date_modify = self.__extract_date_modify()
        self.date_download = self.__extract_date_download()
        self.image_url = self.__extract_image_url()
        self.filename = self.__extract_filename()
        self.title_page = self.__extract_title_page()
        self.title_rss = self.__extract_title_rss()
        self.language = self.__extract_language()
        self.publication = self.__extract_publication()
        self.category = self.__extract_category()
        self.keywords = self.__extract_keywords() 
        self.summary = self.__extract_summary()   
        self.source_domain = self.__extract_source_domain()
        self.source_favicon_url = self.__extract_source_favicon_url()
        self.description = self.__extract_description()

        self.get_dict = self.__serialize()
        print(f"[Newspaper DEBUG __init__] Final extracted article text (first 100 chars): {repr(self.article[:100]) if self.article else 'None'}") 
        print(f"[Newspaper DEBUG __init__] Final extracted headline: {self.headline}") 

    def __validate_initialization(self):
        """Raise an error if no valid data is found from any handler's basic initialization."""
        np_valid = self.__news_please.is_valid()
        ar_valid = self.__article.is_valid()
        so_valid = self.__soup.is_valid() 
        print(f"[Newspaper DEBUG __validate_initialization] NewsPlease valid: {np_valid}, ArticleHandler valid: {ar_valid}, SoupHandler valid: {so_valid}") 
        if not (np_valid or ar_valid or so_valid): 
            raise ValueError("Sorry, the page you are looking for caused all handlers to fail initialization.")

    @staticmethod
    def __extract(*sources):
        """Generic method to extract the first valid value from provided sources."""
        for i, source_value_getter in enumerate(sources): 
            value = source_value_getter 
            print(f"[Newspaper DEBUG __extract] Trying source index {i}. Value (first 50 if str): {repr(value[:50] if isinstance(value, str) else value)}") 
            if isinstance(value, list): 
                if value and value != ['N/A']: 
                    return value
            elif value is not None and value != "" and value != "N/A": 
                return value
        print("[Newspaper DEBUG __extract] All sources yielded no valid value.") 
        return None 

    def __extract_authors(self):
        print("[Newspaper DEBUG __extract_authors] called.") 
        return self.__extract(self.__news_please.authors, self.__article.authors, self.__soup.authors)

    def __extract_date_publish(self):
        print("[Newspaper DEBUG __extract_date_publish] called.") 
        return self.__extract(self.__news_please.date_publish, self.__article.date_publish, self.__soup.date_publish)

    def __extract_date_modify(self):
        print("[Newspaper DEBUG __extract_date_modify] called (uses NewsPleaseHandler).") 
        return self.__news_please.date_modify

    def __extract_date_download(self):
        print("[Newspaper DEBUG __extract_date_download] called (uses NewsPleaseHandler).") 
        return self.__news_please.date_download

    def __extract_image_url(self):
        print("[Newspaper DEBUG __extract_image_url] called (uses NewsPleaseHandler).") 
        return self.__news_please.image_url

    def __extract_filename(self):
        print("[Newspaper DEBUG __extract_filename] called (uses NewsPleaseHandler).") 
        return self.__news_please.filename

    def __extract_article(self):
        print("[Newspaper DEBUG __extract_article] Trying NewsPleaseHandler.article...") 
        news_please_text = self.__news_please.article 
        print(f"[Newspaper DEBUG __extract_article] NewsPleaseHandler.article returned (first 100): {repr(news_please_text[:100]) if news_please_text else 'None'}") 
        print("[Newspaper DEBUG __extract_article] Trying ArticleHandler.article (newspaper4k)...") 
        article_handler_text = self.__article.article 
        print(f"[Newspaper DEBUG __extract_article] ArticleHandler.article (newspaper4k) returned (first 100): {repr(article_handler_text[:100]) if article_handler_text else 'None'}") 
        return self.__extract(news_please_text, article_handler_text)

    def __extract_title_page(self):
        print("[Newspaper DEBUG __extract_title_page] called (uses NewsPleaseHandler).") 
        return self.__news_please.title_page

    def __extract_title_rss(self):
        print("[Newspaper DEBUG __extract_title_rss] called (uses NewsPleaseHandler).") 
        return self.__news_please.title_rss

    def __extract_language(self):
        print("[Newspaper DEBUG __extract_language] called (uses NewsPleaseHandler).") 
        return self.__news_please.language

    def __extract_publication(self):
        print("[Newspaper DEBUG __extract_publication] called.") 
        return self.__extract(self.__article.publication, self.__soup.publisher)

    def __extract_category(self):
        print("[Newspaper DEBUG __extract_category] called.") 
        return self.__extract(self.__article.category, self.__soup.category)

    def __extract_headline(self):
        print("[Newspaper DEBUG __extract_headline] called.") 
        return self.__extract(self.__news_please.headline, self.__article.headline)

    def __extract_keywords(self):
        print("[Newspaper DEBUG __extract_keywords] called (uses ArticleHandler).") 
        return self.__article.keywords or [] 

    def __extract_summary(self):
        print("[Newspaper DEBUG __extract_summary] called (uses ArticleHandler).") 
        return self.__article.summary

    def __extract_source_domain(self):
        print("[Newspaper DEBUG __extract_source_domain] called (uses NewsPleaseHandler).") 
        return self.__news_please.source_domain

    def __extract_source_favicon_url(self):
        print("[Newspaper DEBUG __extract_source_favicon_url] called (uses ArticleHandler).") 
        return self.__article.meta_favicon

    def __extract_description(self): 
        print("[Newspaper DEBUG __extract_description] called.") 
        return self.__extract(self.__news_please.summary, self.__article.summary)

    def __serialize(self):
        """Return a dictionary representation of the article's data."""
        return {
            "headline": self.headline, "author": self.authors, "date_publish": self.date_publish,
            "date_modify": self.date_modify, "date_download": self.date_download,
            "language": self.language, "image_url": self.image_url, "filename": self.filename,
            "description": self.description, "publication": self.publication,
            "category": self.category, "source_domain": self.source_domain,
            "source_favicon_url": self.source_favicon_url, "article": self.article,
            "summary": self.summary, "keyword": self.keywords, 
            "title_page": self.title_page, "title_rss": self.title_rss, "url": self.url
        }