# Nifty News Sentiment Analyzer

A financial intelligence platform tracking sentiment across 22 NIFTY sectors and 252 stocks — ingestion, dual sentiment scoring (VADER + FinBERT), grounded RAG Q&A, price backtesting, and a LangGraph agent that routes questions across all of it.

Built as an ICICI Bank internship project, extended into a full applied-NLP/AI-engineering platform demonstrating retrieval-augmented generation, transformer-based sentiment analysis, statistical backtesting, and agentic tool orchestration on real Indian equity market data.

---

## What it does

Financial news is a leading indicator — narratives shift before prices move. This platform:

- **Ingests** real Indian financial news continuously across three complementary sources, each doing what it's actually good at
- **Scores** every article with both VADER (fast, lexicon-based) and FinBERT (transformer, finance-domain-trained), on the same text window, so the two are genuinely comparable
- **Answers free-form questions** via grounded RAG — semantic retrieval over the corpus, cited generation, no hallucination-by-default
- **Backtests** whether sentiment actually predicts next-day stock returns, via Pearson correlation, comparing VADER's signal against FinBERT's
- **Routes multi-part questions** through a LangGraph agent that decides, autonomously, which of RAG/sentiment-lookup/price-fetch tools a question actually needs — and combines results across tools for genuinely cross-cutting questions

---

## Architecture

```
                            Flask Web App (app.py)
                                       |
        +--------------+--------------+--------------+--------------+
        |              |              |              |              |
   Sector/Stock    Ad-hoc Fetch    /api/ask       /api/agent    /api/update-keys
   Analysis         + Analysis     (RAG Q&A)      (LangGraph)
   (VADER+Gemini)                     |               |
        |               |             v               v
        |               |        rag.py           agent.py
        |               |        BGE embed        router->tool
        |               |        cosine            ->synthesiser
        |               |        retrieval          loop (<=4)
        |               |             |               |
        +---------------+-------------+---------------+
                         |
                         v
              SQLite (WAL mode) -- news_data.db
              scraped_articles, article_sectors, article_chunks
                         ^
                         |
              ingestion.py (standalone, runs independent of Flask)

              Tier A: RSS (daily, free, unlimited)
              Tier B: Google News drip (rate-limited, freshness-targeted)
              Tier C: NewsAPI (on-demand only, budget-tracked)

              Every save -> VADER scored -> RAG-embedded -> FinBERT-scored
              (all delta-safe, all automatic)

              backtest.py -> sentiment(t) vs return(t+1), Pearson r,
                              VADER vs FinBERT, via resolve_tickers.py's
                              verified name->ticker mapping
```

---

## The four phases

### Phase 0 -- Ingestion (foundation)
`ingestion.py` -- one file, three tiers:
- **RSS** (14 publisher feeds -- Economic Times, Moneycontrol, LiveMint, BusinessLine): daily, free, unlimited, captures the fresh news flow
- **Google News search drip**: keyless discovery per stock, encrypted-URL decoding, exponential backoff, keeps every stock's coverage topped up, worst-covered first
- **NewsAPI**: on-demand only, never scheduled -- reserved for when Flask detects thin coverage for a user-requested stock/sector, tracked against a 90/day budget

Every article saved goes through one shared path: URL dedupe, multi-sector tagging (a stock can genuinely belong to multiple sectors -- modeled with a proper many-to-many join table, not a single column), VADER scored immediately, then automatically picked up for RAG embedding and FinBERT scoring -- all delta-safe, so re-running costs nothing when there's nothing new.

### Phase 1 -- Grounded RAG Q&A
`rag.py`:
- Chunking: paragraph-first, ~300 words/50-word overlap, sentence-level fallback for oversized paragraphs
- Embeddings: local `BAAI/bge-small-en-v1.5` via `sentence-transformers` -- no API rate limits, free, runs on CPU
- Storage: SQLite BLOB + NumPy brute-force cosine similarity (sized deliberately -- a few thousand chunks doesn't need a vector database; the migration path exists if that changes)
- Retrieval: SQL metadata pre-filter (stock/sector/date) *then* vector ranking on the survivors, plus a small recency bonus
- Generation: Gemini with a strict grounding prompt -- numbered sources, mandatory citations, explicit instruction to say "the sources don't contain this" rather than guess

### Phase 2 -- FinBERT benchmark + price backtest
`finbert_benchmark.py`: runs `ProsusAI/finbert` (inference only, no training) on every article, on the *same* text window VADER uses (`utils/sentiment_analyzer.py`'s `prepare_scoring_text()` -- one shared source of truth, so the two scorers are never comparing different inputs). Computes agreement %, surfaces real disagreement examples.

`backtest.py`: per stock, `sentiment(t)` correlated against `return(t+1)` -- not same-day (that mostly measures news reacting to price, not predicting it), and returns, not raw price levels (which trend, producing fake correlation from shared drift rather than genuine signal). Filtered to stocks with real article coverage and real trading liquidity. VADER's and FinBERT's series compared head-to-head.

`resolve_tickers.py`: company names in the corpus aren't stock tickers -- this resolves and verifies real NSE symbols against live yfinance data before backtest.py trusts them.

### Phase 3 -- LangGraph agent
`agent.py`: a genuine graph, not a fixed pipeline -- `router -> tool -> router (loop) -> synthesiser`. The router (an LLM call) decides, per question, which of three tools to invoke:
- `rag_answer` -- qualitative why/what-happened questions, grounded with citations
- `sentiment_lookup` -- current average sentiment, computed fresh from the database
- `price_fetch` -- recent returns and volatility, computed fresh from yfinance

Capped at 4 router<->tool round-trips (an agent that can loop must also be guaranteed to stop). Tool failures return text the router can react to, not a crash. A purely qualitative question resolves with one `rag_answer` call, identical to plain RAG; a genuinely cross-cutting question ("did the bad news hurt the stock?") pulls sentiment *and* price and composes both into one answer neither tool alone could produce.

---

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file at the project root:
```
NEWSAPI_ORG_API_KEY=your_key
GEMINI_API_KEY=your_key
FLASK_SECRET_KEY=some_long_random_string
```

Run:
```bash
python app.py
```

Ingestion starts automatically in the background on startup (once/day, safe to leave running alongside development). Or run it standalone, independent of Flask:
```bash
python ingestion.py
```

Before backtesting, resolve real tickers once:
```bash
python resolve_tickers.py
python backtest.py
```

---

## Known, stated limitations

- `related_stock` is single-valued -- an article naming multiple companies credits one; all its relevant *sectors* are still fully tagged via the many-to-many join table
- The ad-hoc analysis route calls NewsAPI directly, bypassing the budget tracker other routes respect -- a known, accepted gap, documented in code
- Backtest correlation thresholds are currently relaxed below the ideal (reflecting the corpus's ingestion history so far) -- reliability improves as more days of history accumulate
- The LangGraph router uses prompted JSON rather than native function-calling, a deliberate choice given constraints on live-testing the exact function-calling schema during development; native function-calling is a reasonable future upgrade