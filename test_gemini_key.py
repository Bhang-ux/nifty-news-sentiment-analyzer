# test_gemini_key.py
import sys
sys.path.insert(0, '.')
import config

print("Key length:", len(config.GEMINI_API_KEY))
print("Is placeholder:", config.GEMINI_API_KEY == config.GEMINI_API_KEY_PLACEHOLDER)
print("First 6 chars:", config.GEMINI_API_KEY[:6])