# utils/sentiment_analyzer.py
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import logging

logger = logging.getLogger(__name__)

# Download VADER lexicon if not already present
try:
    nltk.data.find('sentiment/vader_lexicon.zip')
except LookupError:
    logger.info("Downloading VADER lexicon for NLTK...")
    nltk.download('vader_lexicon', quiet=True) # Set quiet=False for verbose download if issues
except Exception as e: 
    logger.warning(f"Could not verify NLTK VADER lexicon, attempting download: {e}")
    try:
        nltk.download('vader_lexicon', quiet=True)
    except Exception as e_download:
        logger.error(f"Failed to download NLTK VADER lexicon: {e_download}")


_vader_analyzer_instance = None

def get_vader_analyzer():
    global _vader_analyzer_instance
    if _vader_analyzer_instance is None:
        try:
            _vader_analyzer_instance = SentimentIntensityAnalyzer()
        except LookupError: 
            logger.error("VADER lexicon not found after initial check/download attempt. Please ensure it's manually downloaded if issues persist.")
            # Attempt one more time, non-quietly for visibility
            try:
                logger.info("Attempting NLTK VADER lexicon download again (verbose)...")
                nltk.download('vader_lexicon', quiet=False)
                _vader_analyzer_instance = SentimentIntensityAnalyzer()
                logger.info("VADER lexicon successfully downloaded and analyzer initialized.")
            except Exception as e:
                logger.error(f"Critical failure: Failed to initialize SentimentIntensityAnalyzer after second download attempt: {e}")
                return None 
        except Exception as e:
            logger.error(f"Failed to initialize SentimentIntensityAnalyzer: {e}")
            return None
    return _vader_analyzer_instance

def get_vader_sentiment_score(text):
    """
    Analyzes the sentiment of a given text using VADER.
    Returns the compound score (float between -1 and 1).
    Returns 0.0 if analysis fails or text is empty.
    """
    if not text or not isinstance(text, str) or not text.strip():
        return 0.0

    analyzer = get_vader_analyzer()
    if not analyzer:
        logger.warning("VADER analyzer not available. Returning neutral score.")
        return 0.0
        
    try:
        vs = analyzer.polarity_scores(text)
        return vs['compound']
    except Exception as e:
        logger.error(f"Error during VADER sentiment analysis for text '{text[:50]}...': {e}")
        return 0.0

def get_average_vader_score(scores_list):
    """
    Calculates the average of a list of VADER scores.
    Returns 0.0 if the list is empty or contains no valid scores.
    """
    if not scores_list:
        return 0.0
    valid_scores = [s for s in scores_list if isinstance(s, (int, float))]
    if not valid_scores:
        return 0.0
    return sum(valid_scores) / len(valid_scores)

def get_sentiment_label_from_score(score, threshold_positive=0.05, threshold_negative=-0.05):
    """
    Categorizes a sentiment score into 'Positive', 'Negative', or 'Neutral'.
    """
    if not isinstance(score, (int, float)): 
        return "N/A"
    if score > threshold_positive:
        return "Positive"
    elif score < threshold_negative:
        return "Negative"
    else:
        return "Neutral"