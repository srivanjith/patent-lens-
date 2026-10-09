import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings
logger = logging.getLogger("patentlens.database")

Base = declarative_base()

def _get_masked_db_url(url: str) -> str:
    """Safely mask database credentials for startup logs."""
    if not url:
        return "not configured"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname or "unknown"
        port = f":{parsed.port}" if parsed.port else ""
        db_name = parsed.path or ""
        return f"{parsed.scheme}://***:***@{hostname}{port}{db_name}"
    except Exception:
        return "postgresql://***:***@<masked-host>"

IS_POSTGRES = settings.DATABASE_URL.startswith("postgresql")
HAS_PGVECTOR = False

is_production = (getattr(settings, "ENVIRONMENT", "development").lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production")

db_url = settings.DATABASE_URL
if db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
    if not any(x in db_url for x in ["+psycopg2", "+psycopg", "+asyncpg", "+pg8000"]):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1).replace("postgres://", "postgresql+psycopg2://", 1)

if IS_POSTGRES:
    logger.info("Database backend: PostgreSQL")
    logger.info(f"Database host: {_get_masked_db_url(db_url)}")
    try:
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=10,
            max_overflow=20,
            connect_args={"connect_timeout": 5}
        )
        with engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.commit()
                HAS_PGVECTOR = True
                logger.info("Connected to PostgreSQL and verified pgvector extension.")
            except Exception as ve:
                logger.info(f"Connected to PostgreSQL successfully! (pgvector extension note: {ve})")
    except Exception as e:
        logger.warning(f"PostgreSQL connection failed ({_get_masked_db_url(db_url)}: {e}). Switching to SQLite fallback.")
        IS_POSTGRES = False
        SQLITE_URL = "sqlite:///./patentlens.db"
        engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
else:
    logger.info("Database backend: SQLite (Development/Testing)")
    SQLITE_URL = "sqlite:///./patentlens.db"
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def ensure_columns_exist(engine_instance):
    """Ensure newly added columns exist in searches, users, and patents tables across PostgreSQL and SQLite."""
    cols_searches = [
        ("total_results", "INTEGER DEFAULT 0"),
        ("very_high_similarity", "INTEGER DEFAULT 0"),
        ("high_similarity", "INTEGER DEFAULT 0"),
        ("moderate_similarity", "INTEGER DEFAULT 0"),
        ("low_similarity", "INTEGER DEFAULT 0"),
        ("patents_searched", "INTEGER DEFAULT 0"),
        ("patents_retrieved", "INTEGER DEFAULT 0"),
        ("patents_shortlisted", "INTEGER DEFAULT 0"),
        ("patents_deeply_analyzed", "INTEGER DEFAULT 0"),
        ("pipeline_metrics", "TEXT"),
    ]
    cols_search_results = [
        ("analysis_payload", "TEXT"),
    ]
    cols_users = [
        ("is_verified", "BOOLEAN DEFAULT FALSE"),
        ("otp_code", "VARCHAR(6)"),
        ("otp_expires_at", "TIMESTAMP"),
    ]
    cols_patents = [
        ("claims", "TEXT"),
        ("source_type", "VARCHAR(50) DEFAULT 'DATABASE'"),
        ("source_status", "VARCHAR(50) DEFAULT 'DATABASE'"),
        ("document_type", "VARCHAR(50) DEFAULT 'DATABASE RECORD'"),
        ("lens_id", "VARCHAR(100)"),
        ("filing_date", "VARCHAR(50)"),
        ("earliest_priority_date", "VARCHAR(50)"),
        ("simple_family_id", "VARCHAR(100)"),
        ("simple_family_size", "INTEGER DEFAULT 1"),
        ("extended_family_size", "INTEGER DEFAULT 1"),
        ("data_quality_status", "VARCHAR(50) DEFAULT 'LIMITED'"),
        ("cpc_codes", "TEXT"),
        ("ipc_codes", "TEXT"),
        ("jurisdiction", "VARCHAR(20)"),
    ]
    try:
        with engine_instance.connect() as conn:
            for col_name, col_type in cols_searches:
                try:
                    if IS_POSTGRES:
                        conn.execute(text(f"ALTER TABLE searches ADD COLUMN IF NOT EXISTS {col_name} {col_type};"))
                    else:
                        conn.execute(text(f"ALTER TABLE searches ADD COLUMN {col_name} {col_type};"))
                    conn.commit()
                except Exception:
                    pass

            for col_name, col_type in cols_search_results:
                try:
                    if IS_POSTGRES:
                        conn.execute(text(f"ALTER TABLE search_results ADD COLUMN IF NOT EXISTS {col_name} {col_type};"))
                    else:
                        conn.execute(text(f"ALTER TABLE search_results ADD COLUMN {col_name} {col_type};"))
                    conn.commit()
                except Exception:
                    pass

            for col_name, col_type in cols_users:
                try:
                    if IS_POSTGRES:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_type};"))
                    else:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type};"))
                    conn.commit()
                except Exception:
                    pass

            for col_name, col_type in cols_patents:
                try:
                    if IS_POSTGRES:
                        conn.execute(text(f"ALTER TABLE patents ADD COLUMN IF NOT EXISTS {col_name} {col_type};"))
                    else:
                        conn.execute(text(f"ALTER TABLE patents ADD COLUMN {col_name} {col_type};"))
                    conn.commit()
                except Exception:
                    pass
        logger.info("Successfully executed database column migration check.")
    except Exception as e:
        logger.warning(f"Database column migration note: {e}")

# Run schema column checks upon engine initialization
try:
    ensure_columns_exist(engine)
except Exception as e:
    logger.warning(f"Initial schema migration note: {e}")

def get_db():
    """Dependency for obtaining database sessions in FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================================
# MongoDB Engine & Beanie ODM Connection
# ==========================================

mongo_client = None

async def init_mongo():
    global mongo_client
    mongo_url = getattr(settings, "MONGODB_URL", "mongodb://localhost:27017/patentlens")
    db_name = getattr(settings, "MONGODB_DB_NAME", "patentlens")
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from beanie import init_beanie
        from app.models.models import UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc

        logger.info(f"Initializing MongoDB connection to {db_name}...")
        mongo_client = AsyncIOMotorClient(mongo_url)
        await init_beanie(
            database=mongo_client[db_name],
            document_models=[UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc]
        )
        logger.info("MongoDB & Beanie Document ORM initialized successfully.")
    except Exception as e:
        logger.warning(f"MongoDB initialization note: {e}")

async def close_mongo():
    global mongo_client
    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB connection closed.")

