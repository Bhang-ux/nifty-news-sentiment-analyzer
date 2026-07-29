# corpus_eda.py
"""
Run this against your actual news_data.db before deciding chunking params.
Answers exactly the questions that determine chunking strategy:
  - How many articles actually exceed your target chunk size?
  - Does length differ meaningfully by source (rss / gnews-search / newsapi / legacy)?
  - How many are empty/too short to be useful at all?

Usage: python corpus_eda.py   (run from your project root, same place as app.py)
"""

import sys
import os
sys.stdout.reconfigure(encoding='utf-8')  # match your existing Windows cp1252 fix

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
import sqlite3
from utils.database_models import DATABASE_URL

CHUNK_TARGET_WORDS = 300  # your agreed chunking target -- change if you decide differently

# ─── Load everything directly from the DB ──────────────────────────────────
# Connect directly via sqlite3 rather than passing the SQLAlchemy engine to
# pandas -- more reliable across pandas/SQLAlchemy version combinations.
db_path = DATABASE_URL.replace("sqlite:///", "")
conn = sqlite3.connect(db_path)
df = pd.read_sql("""
    SELECT id, headline, article_text, source, related_stock,
           publication_date, download_date
    FROM scraped_articles
""", conn)
conn.close()

print(f"Total rows in scraped_articles: {len(df)}")
print()

# ─── Data quality first -- garbage in, garbage chunked ─────────────────────
df['article_text'] = df['article_text'].fillna('')
df['headline'] = df['headline'].fillna('')
empty_text = (df['article_text'].str.strip() == '').sum()
empty_headline = (df['headline'].str.strip() == '').sum()
print("=== DATA QUALITY ===")
print(f"Rows with empty article_text: {empty_text} ({empty_text/len(df)*100:.1f}%)")
print(f"Rows with empty headline: {empty_headline} ({empty_headline/len(df)*100:.1f}%)")
print("-> These should be EXCLUDED from the RAG corpus entirely, not chunked as empty documents.")
print()

# ─── Word counts ────────────────────────────────────────────────────────────
df['article_word_count'] = df['article_text'].str.split().str.len()
df['headline_word_count'] = df['headline'].str.split().str.len()

# Only look at rows that actually have text for the length stats below
usable = df[df['article_word_count'] > 0].copy()
print(f"Usable rows (non-empty article_text): {len(usable)}")
print()

print("=== ARTICLE BODY LENGTH (words) ===")
desc = usable['article_word_count'].describe(percentiles=[.25, .5, .75, .90, .95, .99])
print(desc.to_string())
print()

print("=== HEADLINE LENGTH (words) ===")
print(usable['headline_word_count'].describe().to_string())
print()

# ─── The number that actually decides chunking strategy ────────────────────
pct_over_target = (usable['article_word_count'] > CHUNK_TARGET_WORDS).mean() * 100
pct_over_2x = (usable['article_word_count'] > CHUNK_TARGET_WORDS * 2).mean() * 100
print(f"=== CHUNKING DECISION NUMBERS (target={CHUNK_TARGET_WORDS} words) ===")
print(f"Articles that exceed {CHUNK_TARGET_WORDS} words (would ever need splitting): {pct_over_target:.1f}%")
print(f"Articles that exceed {CHUNK_TARGET_WORDS*2} words (would need 3+ chunks): {pct_over_2x:.1f}%")
print()

# ─── Breakdown by source -- your own notes flagged legacy as different ─────
print("=== LENGTH BY SOURCE ===")
source_stats = usable.groupby(usable['source'].fillna('legacy_null'))['article_word_count'].agg(
    ['count', 'mean', 'median', 'min', 'max']
).round(1)
print(source_stats.to_string())
print()

# ─── Save a histogram + boxplot for a visual read on the distribution ──────
try:
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={'height_ratios': [3, 1]})

    ax1.hist(usable['article_word_count'], bins=50, color='#4A76C0', edgecolor='black')
    ax1.axvline(CHUNK_TARGET_WORDS, color='red', linestyle='--', label=f'{CHUNK_TARGET_WORDS}-word chunk target')
    ax1.axvline(usable['article_word_count'].median(), color='green', linestyle='--', label='median')
    ax1.set_title('Article body length distribution (words)')
    ax1.set_ylabel('Number of articles')
    ax1.legend()

    ax2.boxplot(usable['article_word_count'], vert=False)
    ax2.set_xlabel('Words')

    plt.tight_layout()
    out_path = os.path.join(PROJECT_ROOT, 'corpus_length_distribution.png')
    plt.savefig(out_path, dpi=150)
    print(f"Saved chart: {out_path}")
except ImportError:
    print("matplotlib not installed -- skipping chart. pip install matplotlib if you want it.")

print()
print("=== RECOMMENDATION (based on the numbers above, not assumed) ===")
if pct_over_target < 20:
    print(f"Only {pct_over_target:.1f}% of articles exceed your {CHUNK_TARGET_WORDS}-word target.")
    print("-> Most articles will be ONE chunk each. Chunking logic mainly needs to handle")
    print("   the minority correctly, not optimize for the common case (already true).")
else:
    print(f"{pct_over_target:.1f}% of articles exceed your {CHUNK_TARGET_WORDS}-word target -- more than expected.")
    print("-> Worth checking WHICH source is driving this (see breakdown above) before finalizing.")