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

is_mongo_primary = getattr(settings, "PRIMARY_DB", "mongodb").lower() == "mongodb"
IS_POSTGRES = settings.DATABASE_URL.startswith("postgresql") and not is_mongo_primary
HAS_PGVECTOR = False
ACTIVE_DB = "sqlite"

is_production = (getattr(settings, "ENVIRONMENT", "development").lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production")

db_url = settings.DATABASE_URL
if db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
    if not any(x in db_url for x in ["+psycopg2", "+psycopg", "+asyncpg", "+pg8000"]):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1).replace("postgres://", "postgresql+psycopg2://", 1)

import tempfile

is_vercel = os.getenv("VERCEL") == "1" or os.getenv("NOW_REGION") is not None

def _get_sqlite_url() -> str:
    """Return a guaranteed writable SQLite database path, falling back to tempdir in serverless/read-only runtimes."""
    if is_production or is_vercel:
        tmp_dir = tempfile.gettempdir()
        safe_path = os.path.normpath(os.path.join(tmp_dir, "patentlens.db")).replace("\\", "/")
        return f"sqlite:///{safe_path}" if safe_path.startswith("/") else f"sqlite:///{safe_path}"

    test_file = os.path.join(".", ".write_test")
    try:
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return "sqlite:///./patentlens.db"
    except Exception:
        tmp_dir = tempfile.gettempdir()
        safe_path = os.path.normpath(os.path.join(tmp_dir, "patentlens.db")).replace("\\", "/")
        return f"sqlite:///{safe_path}" if safe_path.startswith("/") else f"sqlite:///{safe_path}"

SQLITE_URL = _get_sqlite_url()

if is_mongo_primary:
    logger.info("🍃 Primary Database: MongoDB Atlas (Beanie Document ORM)")
    logger.info("📦 Local Relational Store: SQLite")
    engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
    ACTIVE_DB = "sqlite_local"
elif IS_POSTGRES:
    logger.info("Database backend: PostgreSQL (primary)")
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
                logger.info("✅ PostgreSQL connected with pgvector extension.")
            except Exception as ve:
                logger.info(f"✅ PostgreSQL connected. (pgvector extension note: {ve})")
        ACTIVE_DB = "postgresql"
    except Exception as e:
        logger.warning(
            f"⚠️  PostgreSQL connection failed ({_get_masked_db_url(db_url)}: {e}). "
            "Falling back to SQLite. MongoDB will serve as the secondary store — "
            "set MONGODB_URL in environment variables for full dual-DB operation."
        )
        IS_POSTGRES = False
        engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
        ACTIVE_DB = "sqlite_fallback"
else:
    logger.info("Database backend: SQLite (Development/Testing)")
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False}
    )
    ACTIVE_DB = "sqlite"

logger.info(f"[DB] Primary Engine: {'MongoDB Atlas' if is_mongo_primary else ACTIVE_DB}")


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
            if IS_POSTGRES:
                # Batch all column additions into single ALTER TABLE statements per table to avoid dozens of network round-trips
                for tbl_name, col_specs in [
                    ("searches", cols_searches),
                    ("search_results", cols_search_results),
                    ("users", cols_users),
                    ("patents", cols_patents),
                ]:
                    try:
                        add_clauses = [f"ADD COLUMN IF NOT EXISTS {col} {ctype}" for col, ctype in col_specs]
                        sql_stmt = f"ALTER TABLE {tbl_name} {', '.join(add_clauses)};"
                        conn.execute(text(sql_stmt))
                    except Exception as e_tbl:
                        logger.debug(f"PostgreSQL batch column check for {tbl_name}: {e_tbl}")
                conn.commit()
            else:
                for tbl_name, col_specs in [
                    ("searches", cols_searches),
                    ("search_results", cols_search_results),
                    ("users", cols_users),
                    ("patents", cols_patents),
                ]:
                    for col_name, col_type in col_specs:
                        try:
                            conn.execute(text(f"ALTER TABLE {tbl_name} ADD COLUMN {col_name} {col_type};"))
                        except Exception:
                            pass
                conn.commit()
        logger.info("Successfully executed database column migration check.")
    except Exception as e:
        logger.warning(f"Database column migration note: {e}")

# Run schema table & column checks upon engine initialization (skip during fast testing imports)
is_test_env = (getattr(settings, "TESTING", False) or os.getenv("TESTING", "").lower() == "true")

def ensure_database_ready():
    """Ensure all SQL tables exist and initial patent records are present."""
    try:
        Base.metadata.create_all(bind=engine)
        ensure_columns_exist(engine)
        from app.models.models import Patent
        with SessionLocal() as session:
            count = session.query(Patent).count()
            if count == 0:
                logger.info("Database has 0 patents on startup. Auto-seeding default patent records...")
                from scripts.seed_database import seed_patents_if_needed
                seed_patents_if_needed(db=session, force_reseed=False)
    except Exception as e:
        logger.warning(f"Database readiness initialization note: {e}")

if not is_test_env:
    ensure_database_ready()

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
# Event loop captured at init_mongo() time (runs on the main asyncio thread).
# Sync FastAPI route threads use get_app_loop() + run_coroutine_threadsafe().
_app_event_loop = None
_mongo_initialized = False

def get_app_loop():
    """Return the main FastAPI event loop, or None if not yet initialised."""
    return _app_event_loop


async def ensure_mongo_initialized():
    """Idempotently ensure MongoDB is connected, safe for serverless/cold-starts."""
    global _mongo_initialized
    if _mongo_initialized:
        return
    _mongo_initialized = True
    await init_mongo()


async def init_mongo():
    global mongo_client, _app_event_loop
    import asyncio
    mongo_url = getattr(settings, "MONGODB_URL", "mongodb://localhost:27017/patentlens")
    db_name = getattr(settings, "MONGODB_DB_NAME", "patentlens")
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from beanie import init_beanie
        from app.models.models import UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc

        from typing import Any, cast
        logger.info(f"Initializing MongoDB connection to {db_name}...")
        mongo_client = AsyncIOMotorClient(mongo_url)
        await init_beanie(
            database=cast(Any, mongo_client[db_name]),
            document_models=[UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc]
        )
        # Capture the running loop so sync threads can use run_coroutine_threadsafe
        try:
            _app_event_loop = asyncio.get_running_loop()
        except RuntimeError:
            _app_event_loop = asyncio.get_event_loop()
        logger.info("MongoDB & Beanie Document ORM initialized successfully.")
    except Exception as e:
        logger.warning(f"MongoDB initialization note: {e}")


async def close_mongo():
    global mongo_client
    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB connection closed.")

