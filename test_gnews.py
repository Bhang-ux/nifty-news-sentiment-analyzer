import sys
sys.path.insert(0, '.')
from daily_ingestion import fetch_via_gnews_fallback, GNEWS_FALLBACK_AVAILABLE
from utils.database_models import SessionLocal, create_db_and_tables

print("GNews fallback available:", GNEWS_FALLBACK_AVAILABLE)

create_db_and_tables()
db = SessionLocal()
saved = fetch_via_gnews_fallback(db, "Infosys", sector_names=["Nifty IT"], related_stock="Infosys")
print("Saved anything new:", saved)
db.close()