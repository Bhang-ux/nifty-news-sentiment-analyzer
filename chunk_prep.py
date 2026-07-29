# chunk_prep.py
"""
Runs right before chunking. Three hard, deterministic rules -- no scoring,
no manual review of flagged candidates, no judgment calls. Add to the two
lists below as you spot bad domains or need a different length floor/cap.
That's the entire maintenance loop.
 
  1. DOMAIN BLOCKLIST -- known-bad sources excluded entirely, every article
     from them, automatically. (Cricbuzz confirmed wrong-page match.)
  2. MIN LENGTH -- anything under 80 words isn't a real article regardless
     of source (catches the ~702 legacy rows averaging 63 words, and any
     other near-empty extraction, from any source, automatically).
  3. WINSORIZE CAP -- anything over 2000 words (your real 99th percentile
     is 2076 -- see corpus_eda.py) gets front-truncated, not excluded.
     Bounds the 15K-69K-word outliers so one bad row can't explode into
     200+ chunks, without needing to know WHY it's long.
"""
 
MIN_WORDS = 80
WINSORIZE_CAP_WORDS = 2000
 
# Add domains here as you find bad sources. Substring match against
# source_domain -- 'cricbuzz.com' blocks www.cricbuzz.com, m.cricbuzz.com, etc.
BLOCKED_DOMAINS = {
    "cricbuzz.com",
}
 
 
def is_blocked_domain(source_domain: str) -> bool:
    if not source_domain:
        return False
    domain = source_domain.lower()
    return any(blocked in domain for blocked in BLOCKED_DOMAINS)
 
 
def winsorize_text(article_text: str, cap_words: int = WINSORIZE_CAP_WORDS) -> str:
    words = article_text.split()
    if len(words) <= cap_words:
        return article_text
    return ' '.join(words[:cap_words])
 
 
def chunk_ready_text(article) -> str | None:
    """
    article: needs .article_text and .source_domain.
    Returns None if this article should be skipped entirely for RAG,
    otherwise the (possibly capped) text actually ready to chunk.
    """
    if is_blocked_domain(getattr(article, 'source_domain', None)):
        return None
 
    text = article.article_text or ''
    if len(text.split()) < MIN_WORDS:
        return None
 
    return winsorize_text(text)