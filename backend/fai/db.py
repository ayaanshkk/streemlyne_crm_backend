import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH)


def normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if "sslmode" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


# ------------------------------------
# DATABASE CONNECTION
# ------------------------------------
# Single connection - every module (companies, contacts, invoices, proposals,
# quotations, pipeline, etc.) now runs against streemLyne_mt_dev2.
raw_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")

if not raw_url:
    if os.getenv("APP_ENV") == "production":
        raise RuntimeError("DATABASE_URL is not set")
    logging.warning("No DATABASE_URL found. Using SQLite.")
    DATABASE_URL = "sqlite:///./local.db"
    use_sqlite = True
else:
    DATABASE_URL = normalize_url(raw_url)
    use_sqlite = False
    logging.info("FAI module: using hosted PostgreSQL database.")

# ------------------------------------
# ENGINE
# ------------------------------------
if use_sqlite:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        future=True,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=2,
        max_overflow=1,
        pool_timeout=30,
        pool_recycle=300,
        pool_pre_ping=True,
        future=True,
        echo=False,
    )

# ------------------------------------
# SESSION
# ------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False,
)

# Alias: files that import DevSessionLocal keep working unchanged - it's
# the exact same engine as SessionLocal now, not a second connection.
DevSessionLocal = SessionLocal

Base = declarative_base()


# ------------------------------------
# DATABASE SESSION HELPER
# ------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ------------------------------------
# TEST DATABASE CONNECTION
# ------------------------------------
def test_connection():
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'streemLyne_mt_dev2' LIMIT 5"
            ))
            tables = [r[0] for r in result]
            print(f"   ↳ Tables visible: {tables}")
            logging.info("DB connection OK")
            return True
    except Exception as e:
        logging.error("DB connection failed: %s", e)
        print(f"❌ DB connection failed: {e}")
        return False


# ------------------------------------
# DATABASE INITIALIZATION
# ------------------------------------
def init_db():
    try:
        from backend import models  # noqa: F401
        Base.metadata.create_all(bind=engine, checkfirst=True)
        print("✅ Database tables initialized")
        return True
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        import traceback
        traceback.print_exc()
        return False


# ------------------------------------
# CLOSE DATABASE CONNECTIONS
# ------------------------------------
def close_all_sessions():
    try:
        engine.dispose()
        print("✅ All database connections closed")
    except Exception as e:
        print(f"⚠️ Error closing connections: {e}")