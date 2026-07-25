import os
from dotenv import load_dotenv
 
load_dotenv()
 
# Unique placeholder strings unlikely to match real API keys
NEWSAPI_ORG_API_KEY_PLACEHOLDER = "NEWSAPI_ORG_API_KEY_DEFAULT_PLACEHOLDER_2025_XYZ123"
GEMINI_API_KEY_PLACEHOLDER = "GEMINI_API_KEY_DEFAULT_PLACEHOLDER_2025_ABC789"
 
# Load actual API keys from .env, fallback to placeholders if not set.
# IMPORTANT: the first argument is the ENV VAR NAME, never the key value itself.
# Your .env file must define these exact variable names:
#   NEWSAPI_ORG_API_KEY=your_real_newsapi_key_here
#   GEMINI_API_KEY=your_real_gemini_key_here
#   FLASK_SECRET_KEY=some_long_random_string_here
NEWSAPI_ORG_API_KEY = os.getenv("NEWSAPI_ORG_API_KEY", NEWSAPI_ORG_API_KEY_PLACEHOLDER)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY_PLACEHOLDER)
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "DEFAULT_FLASK_SECRET_KEY_2025_RANDOM123")
 