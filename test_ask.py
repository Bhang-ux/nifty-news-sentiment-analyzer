# test_ask.py
import sys
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import rag

result = rag.answer("What's the latest news on TCS?", stock="TCS")
print("\n=== ANSWER ===")
print(result["answer"])
print("\n=== SOURCES ===")
for s in result["sources"]:
    print(f"  [{s['stock']}] {s['headline']} ({s['date']}) - score={s['score']}")