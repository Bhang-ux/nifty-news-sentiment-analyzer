# rag.py
"""
RAG layer: local BGE embeddings, hybrid SQL-plus-vector retrieval, grounded
Gemini generation with citations. One file, matching the project's
one-module philosophy (ingestion.py, chunk_prep.py are the other two).

Built to spec from the completion guide, Section 2.3, integrated against
the actual current schema (utils/database_models.py) and the actual
ingestion.get_recent() for the SQL pre-filter step, rather than a fresh
query -- "reuse existing joins" per the guide.

One deliberate addition beyond the guide: every article is passed through
chunk_prep.chunk_ready_text() before chunking -- domain blocklist, min-length
gate, winsorize cap. The guide's spec doesn't cover the 69K-word-outlier /
wrong-page-extraction problem found during EDA; chunk_prep.py already solves
it, so this reuses it rather than re-solving it here.

CHUNK_WORDS/CHUNK_OVERLAP set to the guide's numbers (300/50) -- note this is
NOT the same as the 500/75 tuned earlier in this session from your real
corpus median (409 words). Following the guide's number since that's what
was asked for; flagging the discrepancy rather than silently picking one.

No LangChain here: the guide's Phase 1 dependency line is
`pip install sentence-transformers` only -- LangChain/LangGraph don't show
up until Phase 3. Chunking below is hand-rolled (paragraph-first, sentence
fallback for oversized paragraphs) to match that.
"""

from __future__ import annotations

import os
import re
import sys
import time
import logging
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
from sqlalchemy import text as sql_text

import config
import ingestion
from utils.database_models import SessionLocal, ScrapedArticle, engine
from chunk_prep import chunk_ready_text

logger = logging.getLogger("rag")

# ─── Spec (guide Section 2.3) ────────────────────────────────────────────
CHUNK_WORDS = 300
CHUNK_OVERLAP = 50
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# BGE's model card recommends this instruction prefix on QUERIES only, never
# on the documents/chunks being embedded -- asymmetric on purpose.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

GEMINI_MODEL_NAME = "gemini-3.5-flash"  # same model gemini_utils.py already uses
RECENCY_WEIGHT = 0.15  # small nudge, not a dominant factor -- semantic score still leads
RECENCY_HALFLIFE_DAYS = 30


# ═══════════════════════════════════════════════════════════════════════════
# Chunking -- hand-rolled, paragraph-first with sentence fallback
# ═══════════════════════════════════════════════════════════════════════════

def chunk_text(text: str, target_words: int = CHUNK_WORDS,
               overlap_words: int = CHUNK_OVERLAP) -> list[str]:
    """
    Paragraph-first: accumulate whole paragraphs up to target_words, carry the
    last overlap_words back into the next chunk for boundary context. A single
    paragraph that alone exceeds target_words falls back to sentence-level
    splitting, so one giant unbroken block still gets split sensibly rather
    than either blowing way past the target or being force-cut mid-sentence.
    """
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []

    def _flush():
        if current:
            chunks.append(' '.join(current))

    for para in paragraphs:
        para_words = para.split()

        if len(para_words) > target_words:
            _flush()
            current[:] = current[-overlap_words:] if overlap_words and current else []
            sentences = re.split(r'(?<=[.!?])\s+', para)
            for sent in sentences:
                sent_words = sent.split()
                if current and len(current) + len(sent_words) > target_words:
                    _flush()
                    current[:] = current[-overlap_words:] if overlap_words else []
                current.extend(sent_words)
            continue

        if current and len(current) + len(para_words) > target_words:
            _flush()
            current[:] = current[-overlap_words:] if overlap_words else []
        current.extend(para_words)

    _flush()
    return chunks


# ═══════════════════════════════════════════════════════════════════════════
# Embeddings -- ONE swappable function, per the guide's comment
# ═══════════════════════════════════════════════════════════════════════════

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading embedding model {EMBED_MODEL} (first call only)...")
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def embed_texts(texts: list[str], is_query: bool = False) -> np.ndarray:
    """
    Returns a (len(texts), dim) float32 array, L2-normalized -- so retrieval's
    cosine similarity is just a dot product / single matmul, per the guide.
    is_query=True prepends BGE's recommended query instruction prefix;
    document/chunk embedding calls should leave it False.
    """
    model = _get_model()
    if is_query:
        texts = [BGE_QUERY_PREFIX + t for t in texts]
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vectors, dtype=np.float32)


# ═══════════════════════════════════════════════════════════════════════════
# Storage
# ═══════════════════════════════════════════════════════════════════════════

def ensure_chunk_table() -> None:
    """article_chunks(id, article_id, chunk_index, chunk_text, embedding BLOB,
    model TEXT). model is stored per row so a future embedder switch is
    detectable (mixed-model corruption) rather than silently corrupting search."""
    with engine.begin() as conn:
        conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS article_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL REFERENCES scraped_articles(id),
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding BLOB NOT NULL,
                model TEXT NOT NULL
            )
        """))
        conn.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS ix_article_chunks_article_id "
            "ON article_chunks(article_id)"))


def embed_new_articles(batch_size: int = 32) -> int:
    """
    Backfill + daily delta in one function: finds articles with zero rows in
    article_chunks and processes only those, so re-running this after new
    articles arrive only embeds what's actually new -- safe to call from
    ingestion's run_daily() every day without re-embedding the whole corpus.
    """
    ensure_chunk_table()
    db = SessionLocal()
    try:
        already_chunked = {
            row[0] for row in
            db.execute(sql_text("SELECT DISTINCT article_id FROM article_chunks")).fetchall()
        }
        all_articles = db.query(ScrapedArticle).all()
        to_process = [a for a in all_articles if a.id not in already_chunked]
        logger.info(f"embed_new_articles: {len(to_process)} articles need embedding "
                    f"(of {len(all_articles)} total, {len(already_chunked)} already done)")

        total_chunks = 0
        skipped_by_filter = 0
        for i, article in enumerate(to_process):
            ready_text = chunk_ready_text(article)  # chunk_prep.py's filter gate
            if ready_text is None:
                skipped_by_filter += 1
                continue
            pieces = chunk_text(ready_text)
            if not pieces:
                continue
            vectors = embed_texts(pieces, is_query=False)
            with engine.begin() as conn:
                for idx, (piece, vec) in enumerate(zip(pieces, vectors)):
                    conn.execute(
                        sql_text("INSERT INTO article_chunks "
                                 "(article_id, chunk_index, chunk_text, embedding, model) "
                                 "VALUES (:aid, :idx, :txt, :emb, :model)"),
                        {"aid": article.id, "idx": idx, "txt": piece,
                         "emb": vec.tobytes(), "model": EMBED_MODEL}
                    )
            total_chunks += len(pieces)
            if (i + 1) % batch_size == 0:
                logger.info(f"embed_new_articles: {i+1}/{len(to_process)} articles processed")

        logger.info(f"embed_new_articles: done. {total_chunks} chunks saved, "
                    f"{skipped_by_filter} articles skipped by chunk_prep filter.")
        return total_chunks
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Retrieval -- SQL pre-filter, then vector ranking, then recency blend
# ═══════════════════════════════════════════════════════════════════════════

def retrieve(question: str, stock: str | None = None, sector: str | None = None,
            days: int | None = None, k: int = 8) -> list[dict]:
    """
    1. SQL pre-filter candidate article ids -- reuses ingestion.get_recent(),
       the same function Flask routes already use, not a fresh query.
    2. Load those articles' chunk vectors into one matrix.
    3. scores = matrix @ query_vector (cosine, since both sides are
       L2-normalized -- dot product IS cosine similarity here).
    4. Blend a small recency bonus, return top-k chunks with full metadata
       for citation display.
    """
    ensure_chunk_table()
    db = SessionLocal()
    try:
        # Step 1: SQL pre-filter. days=None -> effectively "whole corpus" (large window).
        candidate_articles = ingestion.get_recent(
            stock=stock, sector=sector, days=days or 36500, limit=2000)
        candidate_ids = [a.id for a in candidate_articles]  # scalar access, safe post-session-close
        if not candidate_ids:
            return []

        id_list = ','.join(str(i) for i in candidate_ids)
        rows = db.execute(sql_text(
            f"SELECT id, article_id, chunk_index, chunk_text, embedding "
            f"FROM article_chunks WHERE article_id IN ({id_list})")).fetchall()
        if not rows:
            return []

        chunk_ids = [r[0] for r in rows]
        chunk_article_ids = [r[1] for r in rows]
        chunk_texts = [r[3] for r in rows]
        vectors = np.stack([np.frombuffer(r[4], dtype=np.float32) for r in rows])

        # Step 3: cosine via dot product (normalized vectors)
        query_vec = embed_texts([question], is_query=True)[0]
        scores = vectors @ query_vec

        # Re-fetch full article rows through THIS session (not the detached
        # objects from get_recent(), whose own session already closed --
        # their .sectors relationship can't lazy-load anymore after that).
        needed_ids = list(set(chunk_article_ids))
        articles = db.query(ScrapedArticle).filter(ScrapedArticle.id.in_(needed_ids)).all()
        article_meta = {a.id: a for a in articles}

        # Step 4: recency bonus -- small, exponential decay, doesn't override relevance
        now = datetime.utcnow()
        final_scores = scores.copy()
        for i, aid in enumerate(chunk_article_ids):
            article = article_meta.get(aid)
            pub_date = (article.publication_date or article.download_date) if article else None
            if pub_date:
                age_days = max((now - pub_date).days, 0)
                final_scores[i] += RECENCY_WEIGHT * float(np.exp(-age_days / RECENCY_HALFLIFE_DAYS))

        top_idx = np.argsort(-final_scores)[:k]

        results = []
        for idx in top_idx:
            aid = chunk_article_ids[idx]
            article = article_meta.get(aid)
            results.append({
                "chunk_id": chunk_ids[idx],
                "article_id": aid,
                "chunk_text": chunk_texts[idx],
                "score": float(final_scores[idx]),
                "headline": article.headline if article else None,
                "related_stock": article.related_stock if article else None,
                "sectors": [s.sector_name for s in article.sectors] if article else [],
                "publication_date": article.publication_date if article else None,
                "source_domain": article.source_domain if article else None,
                "url": article.url if article else None,
            })
        return results
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Generation -- strict grounding, numbered citations
# ═══════════════════════════════════════════════════════════════════════════

def build_prompt(question: str, chunks: list[dict]) -> str:
    """Exact template from the completion guide, Section 2.4."""
    lines = [
        "Answer the question using ONLY the numbered sources below.",
        "Cite every claim as [1], [2]. If the sources do not contain",
        "the answer, say exactly that -- do not use outside knowledge.",
        "",
    ]
    for i, c in enumerate(chunks, 1):
        date_str = (c["publication_date"].strftime("%Y-%m-%d")
                    if c.get("publication_date") else "date unknown")
        sector_str = c["sectors"][0] if c.get("sectors") else "N/A"
        stock_str = c.get("related_stock") or "N/A"
        domain_str = c.get("source_domain") or "unknown source"
        lines.append(f"[{i}] ({stock_str} | {sector_str} | {date_str} | {domain_str})")
        lines.append(c["chunk_text"])
        lines.append("")
    lines.append(f"Question: {question}")
    return "\n".join(lines)


def answer(question: str, stock: str | None = None, sector: str | None = None,
          days: int | None = None, k: int = 8) -> dict:
    """Returns {"answer": str, "sources": [...]}. The Flask /api/ask route
    calls this directly."""
    start = time.time()
    chunks = retrieve(question, stock=stock, sector=sector, days=days, k=k)

    if not chunks:
        result = {"answer": "No relevant articles found in the corpus for this question.",
                  "sources": []}
        log_query(question, [], [], time.time() - start)
        return result

    prompt = build_prompt(question, chunks)

    from google import genai
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model='gemini-3.5-flash',
        contents=prompt,
        config=genai.types.GenerateContentConfig(temperature=0.2)
    )
    answer_text = (response.text or "").strip()

    sources = [{
        "headline": c["headline"],
        "url": c["url"],
        "date": c["publication_date"].strftime("%Y-%m-%d") if c.get("publication_date") else None,
        "stock": c["related_stock"],
        "score": round(c["score"], 3),
    } for c in chunks]

    latency = time.time() - start
    log_query(question, [c["chunk_id"] for c in chunks], [c["score"] for c in chunks], latency)

    return {"answer": answer_text, "sources": sources}


def log_query(question: str, chunk_ids: list[int], scores: list[float], latency: float) -> None:
    """Observability -- every query's retrieved chunks and scores, per the guide's
    'log every skip / every query' lesson from the ingestion war stories."""
    top_score = max(scores) if scores else 0.0
    logger.info(f"RAG query: '{question[:80]}' | {len(chunk_ids)} chunks | "
                f"top_score={top_score:.3f} | latency={latency:.2f}s | chunk_ids={chunk_ids}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')
    print("Backfilling embeddings for all un-chunked articles...")
    n = embed_new_articles()
    print(f"Done. {n} chunks embedded.")