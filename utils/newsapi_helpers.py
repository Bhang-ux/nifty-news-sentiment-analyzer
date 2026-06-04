# utils/newsapi_helpers.py
import logging
from newsapi import NewsApiClient
import time
# from datetime import timedelta # Not directly used here but often useful with dates
from .sentiment_analyzer import get_vader_sentiment_score 

logger = logging.getLogger(__name__) # Ensures it uses the app's logger config

def get_newsapi_org_client(api_key, append_log_func=None):
    log_msg_prefix = "[NewsAPIClient]"
    # Use a consistent local logger function name
    def _log_relay(message, level='info'):
        full_message = f"{log_msg_prefix} {message}"
        if level.lower() == 'error': logger.error(full_message)
        elif level.lower() == 'warning': logger.warning(full_message)
        else: logger.info(full_message)
        if append_log_func: append_log_func(message, level.upper())

    # Added more common placeholder variations
    if not api_key or api_key in ["YOUR_NEWSAPI_ORG_API_KEY_HERE", "YOUR_NEWSAPI_KEY_HERE", ""]:
        msg = "NewsAPI.org key is missing or a placeholder. Client not initialized."
        _log_relay(msg, 'warning')
        return None, msg
    try:
        client = NewsApiClient(api_key=api_key)
        _log_relay("NewsAPI.org client initialized successfully.")
        return client, None
    except Exception as e:
        err_msg = f"Failed to initialize NewsAPI.org client: {e}"
        _log_relay(err_msg, 'error')
        return None, str(e)

def _process_newsapi_response(
    response_articles,
    max_articles_to_return,
    from_date_str_for_fallback, # Used if 'publishedAt' is missing
    log_func # The passed-in contextual logger (e.g., _local_log or _log_relay)
):
    """Helper function to process articles from NewsAPI response."""
    articles_data = []
    unique_urls = set()
    if not response_articles: # Handle empty list early
        if log_func: log_func("No articles received from NewsAPI to process.", "DEBUG")
        return articles_data

    for article_idx, article in enumerate(response_articles):
        if len(articles_data) >= max_articles_to_return:
            if log_func: log_func(f"Reached max_articles_to_return limit ({max_articles_to_return}). Stopping processing NewsAPI articles.", "INFO")
            break
        
        url = article.get('url')
        # Skip if no URL or duplicate
        if not url or url in unique_urls:
            if log_func and url: log_func(f"Skipping duplicate/invalid URL from NewsAPI: {url}", "DEBUG")
            elif log_func and not url: log_func(f"Skipping NewsAPI article {article_idx+1} (no URL).", "DEBUG")
            continue
        unique_urls.add(url)

        title = article.get('title', "") or ""
        description = article.get('description', "") or ""
        # NewsAPI 'content' is often truncated and ends with "[+XXXX chars]"
        content_full = article.get('content', "") or "" 
        
        # Construct best available text for analysis
        text_for_analysis = title
        
        # Prioritize full 'content' if it's substantial, otherwise use description
        # A more robust way to check if 'content' is useful
        content_cleaned = ""
        if content_full:
            # Remove "[+... chars]" often at the end of NewsAPI 'content'
            content_cleaned = content_full.rsplit('[+', 1)[0].strip()
            # Sometimes the content is just the description or title again, or very short
            if len(content_cleaned) < 50 or content_cleaned == description or content_cleaned == title:
                content_cleaned = "" # Discard if not significantly different or too short

        if content_cleaned: # If cleaned 'content' is good
            text_for_analysis += (". " if title and not title.endswith(('.', '!', '?')) else " ") + content_cleaned
        elif description: # Fallback to description
            text_for_analysis += (". " if title and not title.endswith(('.', '!', '?')) else " ") + description
        
        text_for_analysis_stripped = text_for_analysis.strip()
        
        # Ensure we have something more than just a period if title was empty
        if text_for_analysis_stripped and text_for_analysis_stripped != ".":
            vader_score = get_vader_sentiment_score(text_for_analysis_stripped)
            articles_data.append({
                'content': text_for_analysis_stripped, # This is what LLM will see
                'date': article.get('publishedAt', from_date_str_for_fallback).split('T')[0], # Use fallback if needed
                'uri': url,
                'source': article.get('source', {}).get('name', 'NewsAPI.org'), # Be specific
                'vader_score': vader_score,
                'title': title, # Keep original title for display if needed
                'description': description # Keep original description
            })
        elif log_func:
            log_func(f"Skipping NewsAPI article {url_idx+1} (no usable text after processing). URL: {url}, Title: '{title[:50]}...'", "DEBUG")

    return articles_data


def fetch_newsapi_articles( # Generic fetcher for both sector and stock from NewsAPI
    newsapi_client,
    target_name_for_log, # For logging context e.g., "Nifty IT" or "TCS"
    query_keywords_list, # Main keywords for the target
    context_keywords_list, # General context keywords like "India", "NSE"
    from_date_obj,
    to_date_obj,
    max_articles_to_fetch=10, # Max *processed* articles to return
    append_log_func=None # For UI logging relay
):
    log_msg_prefix_local = f"[NewsAPIHelper][Target: {target_name_for_log}]"
    def _local_log_relay(message, level='info'): # Renamed to avoid conflict
        full_message = f"{log_msg_prefix_local} {message}"
        if level.lower() == 'error': logger.error(full_message)
        elif level.lower() == 'warning': logger.warning(full_message)
        else: logger.info(full_message)
        if append_log_func: append_log_func(message, level.upper())

    if not newsapi_client:
        msg = "NewsAPI client not available for fetching."
        _local_log_relay(msg, 'warning')
        return [], msg

    # Ensure keywords are properly quoted for exact phrases or ORed
    # Example: (("Infosys" OR "Infosys results") AND ("India" OR "NSE"))
    main_query_parts = [f'"{k.strip()}"' for k in query_keywords_list if k and k.strip()]
    if not main_query_parts:
        _local_log_relay("No valid main keywords for NewsAPI query construction.", "warning")
        return [], "No valid main keywords provided for NewsAPI query."
    # Join with OR, then wrap the whole thing in parentheses if multiple parts
    main_query_formatted = f"({' OR '.join(main_query_parts)})" if len(main_query_parts) > 1 else main_query_parts[0]


    context_query_parts = [f'"{k.strip()}"' for k in context_keywords_list if k and k.strip()]
    context_query_formatted = f"({' OR '.join(context_query_parts)})" if len(context_query_parts) > 1 else (context_query_parts[0] if context_query_parts else "")
    
    query_string = main_query_formatted
    if context_query_formatted:
        query_string += f" AND {context_query_formatted}" # AND has higher precedence than OR, so parentheses are important
    
    from_date_str = from_date_obj.strftime('%Y-%m-%d')
    to_date_str = to_date_obj.strftime('%Y-%m-%d')
    
    articles_data = []
    error_message_user = None
    # NewsAPI page_size max is 100.
    # We might fetch more than max_articles_to_fetch initially to account for filtering later.
    # Let's aim to fetch slightly more if max_articles_to_fetch is small, but cap at API limits.
    page_size_for_api = min(max(max_articles_to_fetch * 2, 20), 100) 

    _local_log_relay(f"Fetching NewsAPI. Query: '{query_string}', Dates: {from_date_str} to {to_date_str}, Target PageSize: {page_size_for_api}", "DEBUG")

    try:
        all_articles_response = newsapi_client.get_everything(
            q=query_string,
            from_param=from_date_str,
            to=to_date_str,
            language='en',
            sort_by='relevancy', # 'publishedAt' for freshest, 'relevancy' might be better for specific targets
            page_size=page_size_for_api # Ask for up to this many
        )

        if all_articles_response['status'] == 'ok':
            fetched_api_articles = all_articles_response['articles']
            _local_log_relay(f"NewsAPI returned {all_articles_response['totalResults']} total results, received {len(fetched_api_articles)} articles in this API call.", "INFO")
            
            # _process_newsapi_response will internally limit to max_articles_to_fetch
            articles_data = _process_newsapi_response(
                fetched_api_articles, 
                max_articles_to_fetch, 
                from_date_str, # Fallback date string
                _local_log_relay # Pass the contextual logger
            )
            _local_log_relay(f"Processed and returning {len(articles_data)} unique, usable articles from NewsAPI.", "INFO")
        else:
            api_err_code = all_articles_response.get('code', 'N/A')
            api_err_msg = all_articles_response.get('message', 'Unknown NewsAPI error')
            error_message_user = f"NewsAPI.org Error: {api_err_msg} (Code: {api_err_code})"
            _local_log_relay(error_message_user, 'error')
            
            if api_err_code == 'rateLimited':
                _local_log_relay("Rate limited by NewsAPI. Consider pausing or reducing request frequency.", 'warning')
            elif api_err_code == 'sourcesTooOld' or 'maximumAllowedDate' in api_err_code or \
                 (api_err_msg and 'too far in the past' in api_err_msg.lower()):
                _local_log_relay(f"Query date range ({from_date_str} to {to_date_str}) might be too old for NewsAPI free/developer tier.", 'warning')
                error_message_user = f"NewsAPI: Date range may be too old ({from_date_str} to {to_date_str}). Max is usually ~30 days back for free/dev tier."
            # Add other specific error code handling if needed

    except Exception as e:
        err_msg = f"An unexpected exception occurred during NewsAPI fetch: {str(e)}" # Log more of the error
        _local_log_relay(err_msg, 'error')
        logger.exception(f"{log_msg_prefix_local} Full NewsAPI Fetch Exception Details") # Log full trace for server logs
        error_message_user = f"NewsAPI.org fetch exception: {str(e)[:100]}" # User-friendly part
    
    time.sleep(1.2) # API politeness - consider making this configurable
    return articles_data, error_message_user

# Keep your original fetch_sector_news_newsapi and fetch_stock_news_newsapi
# if they are substantially different or called from other places (like batch analysis).
# The new `fetch_newsapi_articles` is designed to be more generic for the adhoc route.
# If fetch_sector_news_newsapi and fetch_stock_news_newsapi are just wrappers around
# the same core logic, you could refactor them to use fetch_newsapi_articles.

# For example, if your app.py's batch sector analysis needs `fetch_sector_news_newsapi`:
def fetch_sector_news_newsapi( # Kept for compatibility if called from old routes
    newsapi_client,
    sector_name, 
    sector_keywords_list, 
    country_keywords_list, 
    from_date_obj,
    to_date_obj,
    max_articles_to_fetch=20, 
    append_log_func=None
):
    # This function can now directly call the generic one
    return fetch_newsapi_articles(
        newsapi_client=newsapi_client,
        target_name_for_log=f"Sector: {sector_name}",
        query_keywords_list=sector_keywords_list,
        context_keywords_list=country_keywords_list,
        from_date_obj=from_date_obj,
        to_date_obj=to_date_obj,
        max_articles_to_fetch=max_articles_to_fetch,
        append_log_func=append_log_func
    )

def fetch_stock_news_newsapi( # Kept for compatibility if called from old routes
    newsapi_client,
    stock_name, 
    stock_specific_keywords, 
    country_keywords_list, 
    from_date_obj,
    to_date_obj,
    max_articles_to_fetch=5, 
    append_log_func=None
):
    return fetch_newsapi_articles(
        newsapi_client=newsapi_client,
        target_name_for_log=f"Stock: {stock_name}",
        query_keywords_list=stock_specific_keywords,
        context_keywords_list=country_keywords_list,
        from_date_obj=from_date_obj,
        to_date_obj=to_date_obj,
        max_articles_to_fetch=max_articles_to_fetch,
        append_log_func=append_log_func
    )