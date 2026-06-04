Nifty News Sentiment Analyzer

Real-time Indian equity news intelligence platform — scrapes, scores, and analyses financial news sentiment across NIFTY sectors and individual stocks using dual NLP engines (VADER + Google Gemini).

Built as part of an ICICI Bank internship project to demonstrate applied NLP, web scraping, and financial data engineering on Indian equity markets.

What It Does
Financial news is a leading indicator — narratives shift before prices move. This platform:

Aggregates real Indian financial news from multiple sources (NewsAPI, GNews, on-demand fetching)
Scores every article using VADER (fast lexical NLP) for immediate sentiment scores
Sends article batches to Google Gemini for deep contextual analysis — themes, risks, opportunities
Presents daily sentiment trend charts, Gemini AI summaries, and per-article breakdowns
Supports both sector-level (Nifty IT, Nifty Bank, etc.) and stock-level (TCS, HDFC Bank, etc.) analysis
Allows on-demand article fetching for any stock/sector — fetches fresh articles in real time


Architecture
┌─────────────────────────────────────────────────────────┐
│                    Flask Web App                         │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Sector Batch │  │ Stock Drill  │  │  Ad-hoc       │  │
│  │ Analysis     │  │ Down         │  │  Fetch+Analyse│  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
└─────────┼─────────────────┼──────────────────┼──────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│  SQLite DB      │  │  VADER Scorer   │  │ OnDemandFetcher  │
│  (news_data.db) │  │  (nltk)         │  │ GNews + httpx    │
│  567+ articles  │  │  Instant score  │  │ newspaper4k      │
└────────┬────────┘  └────────┬────────┘  └──────────────────┘
         │                   │
         ▼                   ▼
┌─────────────────────────────────────────┐
│         Google Gemini API               │
│  Deep analysis: themes, risks,          │
│  opportunities, sentiment summary       │
└─────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│         Frontend (Chart.js)             │
│  Daily sentiment line chart             │
│  Per-article VADER score cards          │
│  Gemini AI analysis panel               │
└─────────────────────────────────────────┘

Tech Stack
LayerTechnologyWeb FrameworkFlask 3.1Database ORMSQLAlchemy 1.4 + SQLiteSentiment (Fast)VADER (nltk)Sentiment (Deep)Google Gemini 2.5 ProNews Source 1NewsAPI.orgNews Source 2GNews (Google News RSS)Article Fetchinghttpx (async) + newspaper4kJS RenderingPlaywright (Chromium headless)Frontend ChartsChart.jsStock PricesyfinanceData Processingpandas, numpy

Project Structure
nifty-news-sentiment-analyzer/
├── app.py                          # Flask app — all routes and business logic
├── config.py                       # Loads API keys from .env (never hardcoded)
├── on_demand_fetcher.py            # Article fetcher using GNews + httpx (replaces Scrapy)
├── requirements.txt                # Minimal clean dependencies
├── .env.example                    # Template for API keys
│
├── utils/
│   ├── database_models.py          # SQLAlchemy ScrapedArticle model
│   ├── db_crud.py                  # Database query functions
│   ├── sentiment_analyzer.py       # VADER scoring
│   ├── gemini_utils.py             # Gemini API calls + NIFTY sector config
│   └── newsapi_helpers.py          # NewsAPI.org integration
│
├── templates/
│   └── index.html                  # Single-page Flask template
│
├── static/
│   ├── js/main.js                  # Frontend JS — form handling, Chart.js rendering
│   └── css/style.css               # Styling
│
└── news_scrapers/                  # Scrapy project (Moneycontrol spider)
    └── news_scrapers/
        └── spiders/
            └── moneycontrol_spider.py   # Spider (currently blocked by Moneycontrol)

Setup & Installation
Prerequisites

Python 3.10+
A free Gemini API key
A free NewsAPI.org key (100 requests/day free tier)

1. Clone and install
bashgit clone https://github.com/YOUR_USERNAME/nifty-news-sentiment-analyzer.git
cd nifty-news-sentiment-analyzer

python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
python -m nltk.downloader vader_lexicon
2. Configure API keys
bashcp .env.example .env
Edit .env:
GEMINI_API_KEY=your_google_gemini_api_key
NEWSAPI_ORG_API_KEY=your_newsapi_org_key
FLASK_SECRET_KEY=any_long_random_string
3. Populate the news database
bashpython populate_from_newsapi.py
This fetches ~500-700 articles covering all major NIFTY sectors (IT, Bank, FMCG, Auto, Pharma, Energy, Metal) for the last 30 days. Takes ~30 seconds.
4. Run the app
bashpython -m flask run --port=5003
Open http://localhost:5003

How to Use
Batch Sector Analysis

Select "Batch Sector Sentiment Analysis (DB)" from Operation Mode
Pick one or more sectors (e.g. Nifty Bank, Nifty IT)
Set date range
Click Run Operation

Shows: average VADER sentiment, Gemini sector summary, article count, risk/opportunity breakdown.
Stock Drill-Down
After running sector analysis, expand any sector result and select individual stocks to get stock-specific sentiment.
Ad-hoc Analysis + Fresh Scrape

Select "Ad-hoc Stock/Sector Analysis (+Scrape)" from Operation Mode
Set Target Type (Stock or Sector) and enter a name (e.g. TCS, Nifty Energy)
Check "Trigger Fresh Scrape" to fetch articles published in your date range in real time
Click Run Operation

The on-demand fetcher searches GNews, fetches full article text via httpx, scores with VADER, and sends to Gemini — all live.

Features

15 NIFTY sectors covered: IT, Bank, FMCG, Auto, Pharma, Energy, Financial Services, Metal, Realty, CPSE, Commodities, Consumer Durables, Healthcare, Infrastructure, Media
150+ stocks individually configurable
Dual NLP pipeline: VADER for speed, Gemini for depth
Daily sentiment chart: spot trend reversals visually
On-demand fetching: get fresh articles for any target in real time
Session-based API key management: update keys without restarting
Processing log: real-time UI log of every operation step


API Keys & Cost
ServiceFree TierUsed ForGoogle Gemini1,500 req/day (Flash), 50/day (Pro)Deep sentiment analysisNewsAPI.org100 req/day, last 30 daysBulk article populationGNews100 req/dayOn-demand article searchyfinanceUnlimited (rate limited)Stock price chart overlay
The app works without Gemini (VADER still scores everything) and without NewsAPI (GNews still fetches on demand).

Known Limitations

Moneycontrol spider blocked: The Scrapy spider for Moneycontrol returns "Access Denied" — replaced by GNews + httpx pipeline which works reliably.
NewsAPI truncation: Free tier truncates article content to 200 characters, reducing VADER accuracy slightly. GNews on-demand fetches full text.
Gemini quota: Free tier resets daily at midnight UTC. VADER analysis always works regardless.


Future Upgrades

 FinBERT: Replace VADER with HuggingFace FinBERT (fine-tuned on financial text) for higher accuracy
 Article clustering: sentence-transformers + KMeans to auto-group articles by topic
 APScheduler: Automated nightly article refresh at 2 AM
 Alembic migrations: Schema versioning for safe DB upgrades
 Economic Times spider: Second Scrapy spider for wider news coverage
 Named Entity Recognition: Auto-extract company names from articles


License
MIT License — free to use, modify, and distribute.