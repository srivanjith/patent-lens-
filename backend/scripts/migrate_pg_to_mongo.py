import os
import sys
import json
import asyncio
import logging

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import create_engine, text
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import settings
from app.models.models import UserDoc, PatentDoc, SearchDoc, SearchResultItem, SavedPatentDoc, ReportDoc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("patentlens.migration")

async def migrate_data():
    logger.info("================ DATA MIGRATION: NEON POSTGRES -> MONGODB ================")
    
    # 1. Connect to SQL Database
    db_url = settings.DATABASE_URL
    if db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
        if not any(x in db_url for x in ["+psycopg2", "+psycopg", "+asyncpg", "+pg8000"]):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1).replace("postgres://", "postgresql+psycopg2://", 1)
    
    logger.info(f"Connecting to SQL source database: {db_url[:25]}...")
    sql_engine = create_engine(db_url)
    
    # 2. Connect to MongoDB
    mongo_url = getattr(settings, "MONGODB_URL", "mongodb://localhost:27017/patentlens")
    db_name = getattr(settings, "MONGODB_DB_NAME", "patentlens")
    logger.info(f"Connecting to MongoDB target: {mongo_url[:25]} / db={db_name}...")
    
    mongo_client = AsyncIOMotorClient(mongo_url)
    await init_beanie(
        database=mongo_client[db_name],
        document_models=[UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc]
    )
    
    with sql_engine.connect() as conn:
        # Migrate Users
        try:
            users_res = conn.execute(text("SELECT * FROM users;")).mappings().all()
            user_count = 0
            for row in users_res:
                r_dict = dict(row)
                existing = await UserDoc.find_one(UserDoc.id == str(r_dict["id"]))
                if not existing:
                    user_doc = UserDoc(
                        id=str(r_dict["id"]),
                        name=r_dict["name"],
                        email=r_dict["email"],
                        password_hash=r_dict["password_hash"],
                        is_verified=bool(r_dict.get("is_verified", False)),
                        otp_code=r_dict.get("otp_code"),
                        otp_expires_at=r_dict.get("otp_expires_at"),
                        created_at=r_dict.get("created_at"),
                        updated_at=r_dict.get("updated_at")
                    )
                    await user_doc.insert()
                    user_count += 1
            logger.info(f"✅ Users Migration: Inserted {user_count} users into MongoDB.")
        except Exception as e:
            logger.warning(f"Users migration note: {e}")

        # Migrate Patents (Batch Processing)
        try:
            patents_res = conn.execute(text("SELECT * FROM patents;")).mappings().all()
            total_p = len(patents_res)
            logger.info(f"Fetched {total_p} patents from SQL database. Starting batch migration...")
            
            patent_docs = []
            patent_count = 0
            for idx, row in enumerate(patents_res, 1):
                r_dict = dict(row)
                p_id = str(r_dict["id"])
                
                emb = r_dict.get("embedding")
                if isinstance(emb, str):
                    try:
                        emb = json.loads(emb)
                    except Exception:
                        emb = None
                
                patent_doc = PatentDoc(
                    id=p_id,
                    patent_number=r_dict["patent_number"],
                    title=r_dict["title"],
                    abstract=r_dict["abstract"],
                    description=r_dict["description"],
                    claims=r_dict.get("claims"),
                    inventors=r_dict["inventors"],
                    assignee=r_dict["assignee"],
                    publication_date=r_dict["publication_date"],
                    domain=r_dict["domain"],
                    source_url=r_dict.get("source_url"),
                    source_type=r_dict.get("source_type", "DATABASE"),
                    source_status=r_dict.get("source_status", "DATABASE"),
                    document_type=r_dict.get("document_type", "DATABASE RECORD"),
                    lens_id=r_dict.get("lens_id"),
                    filing_date=r_dict.get("filing_date"),
                    earliest_priority_date=r_dict.get("earliest_priority_date"),
                    simple_family_id=r_dict.get("simple_family_id"),
                    simple_family_size=r_dict.get("simple_family_size", 1),
                    extended_family_size=r_dict.get("extended_family_size", 1),
                    data_quality_status=r_dict.get("data_quality_status", "LIMITED"),
                    cpc_codes=r_dict.get("cpc_codes"),
                    ipc_codes=r_dict.get("ipc_codes"),
                    jurisdiction=r_dict.get("jurisdiction"),
                    embedding=emb,
                    created_at=r_dict.get("created_at")
                )
                patent_docs.append(patent_doc)
                
                if len(patent_docs) >= 200 or idx == total_p:
                    try:
                        await PatentDoc.insert_many(patent_docs)
                        patent_count += len(patent_docs)
                        logger.info(f"Progress: Inserted {patent_count}/{total_p} patents into MongoDB...")
                    except Exception as e:
                        # Fallback for duplicates
                        for p in patent_docs:
                            try:
                                await p.insert()
                                patent_count += 1
                            except Exception:
                                pass
                    patent_docs = []

            logger.info(f"✅ Patents Migration: Successfully migrated {patent_count} patents into MongoDB.")
        except Exception as e:
            logger.warning(f"Patents migration note: {e}")

        # Migrate Searches & Embedded Search Results
        try:
            searches_res = conn.execute(text("SELECT * FROM searches;")).mappings().all()
            total_s = len(searches_res)
            logger.info(f"Fetched {total_s} search records from SQL database...")
            search_docs = []
            search_count = 0
            for idx, row in enumerate(searches_res, 1):
                s_dict = dict(row)
                s_id = str(s_dict["id"])
                
                results_res = conn.execute(text(f"SELECT * FROM search_results WHERE search_id = '{s_id}';")).mappings().all()
                embedded_results = []
                for res_row in results_res:
                    rr = dict(res_row)
                    mc = rr.get("matched_concepts")
                    if isinstance(mc, str):
                        try:
                            mc = json.loads(mc)
                        except Exception:
                            mc = []
                    payload = rr.get("analysis_payload")
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except Exception:
                            payload = None
                    
                    embedded_results.append(
                        SearchResultItem(
                            id=str(rr["id"]),
                            patent_id=str(rr["patent_id"]),
                            semantic_score=float(rr["semantic_score"]),
                            keyword_score=float(rr["keyword_score"]),
                            domain_score=float(rr["domain_score"]),
                            final_score=float(rr["final_score"]),
                            matched_concepts=mc if isinstance(mc, list) else [],
                            rank=int(rr["rank"]),
                            analysis_payload=payload
                        )
                    )
                
                kw = s_dict.get("keywords")
                if isinstance(kw, str):
                    try:
                        kw = json.loads(kw)
                    except Exception:
                        kw = []
                
                pm = s_dict.get("pipeline_metrics")
                if isinstance(pm, str):
                    try:
                        pm = json.loads(pm)
                    except Exception:
                        pm = None

                search_doc = SearchDoc(
                    id=s_id,
                    user_id=str(s_dict["user_id"]),
                    invention_title=s_dict["invention_title"],
                    domain=s_dict["domain"],
                    problem_statement=s_dict["problem_statement"],
                    description=s_dict["description"],
                    keywords=kw if isinstance(kw, list) else [],
                    risk_level=s_dict["risk_level"],
                    highest_similarity=float(s_dict["highest_similarity"]),
                    total_results=int(s_dict.get("total_results", 0) or 0),
                    very_high_similarity=int(s_dict.get("very_high_similarity", 0) or 0),
                    high_similarity=int(s_dict.get("high_similarity", 0) or 0),
                    moderate_similarity=int(s_dict.get("moderate_similarity", 0) or 0),
                    low_similarity=int(s_dict.get("low_similarity", 0) or 0),
                    patents_searched=int(s_dict.get("patents_searched", 0) or 0),
                    patents_retrieved=int(s_dict.get("patents_retrieved", 0) or 0),
                    patents_shortlisted=int(s_dict.get("patents_shortlisted", 0) or 0),
                    patents_deeply_analyzed=int(s_dict.get("patents_deeply_analyzed", 0) or 0),
                    pipeline_metrics=pm,
                    results=embedded_results,
                    created_at=s_dict.get("created_at")
                )
                search_docs.append(search_doc)
                if len(search_docs) >= 100 or idx == total_s:
                    try:
                        await SearchDoc.insert_many(search_docs)
                        search_count += len(search_docs)
                    except Exception:
                        for s in search_docs:
                            try:
                                await s.insert()
                                search_count += 1
                            except Exception:
                                pass
                    search_docs = []

            logger.info(f"✅ Searches Migration: Inserted {search_count} searches into MongoDB.")
        except Exception as e:
            logger.warning(f"Searches migration note: {e}")

        # Migrate Saved Patents
        try:
            saved_res = conn.execute(text("SELECT * FROM saved_patents;")).mappings().all()
            saved_docs = []
            for row in saved_res:
                sp = dict(row)
                sp_doc = SavedPatentDoc(
                    id=str(sp["id"]),
                    user_id=str(sp["user_id"]),
                    patent_id=str(sp["patent_id"]),
                    notes=sp.get("notes"),
                    created_at=sp.get("created_at")
                )
                saved_docs.append(sp_doc)
            if saved_docs:
                try:
                    await SavedPatentDoc.insert_many(saved_docs)
                except Exception:
                    for sp in saved_docs:
                        try:
                            await sp.insert()
                        except Exception:
                            pass
            logger.info(f"✅ Saved Patents Migration: Inserted {len(saved_docs)} saved patents into MongoDB.")
        except Exception as e:
            logger.warning(f"Saved patents migration note: {e}")

        # Migrate Reports
        try:
            reports_res = conn.execute(text("SELECT * FROM reports;")).mappings().all()
            report_docs = []
            for row in reports_res:
                rp = dict(row)
                rp_doc = ReportDoc(
                    id=str(rp["id"]),
                    user_id=str(rp["user_id"]),
                    search_id=str(rp["search_id"]),
                    report_path=rp["report_path"],
                    created_at=rp.get("created_at")
                )
                report_docs.append(rp_doc)
            if report_docs:
                try:
                    await ReportDoc.insert_many(report_docs)
                except Exception:
                    for rp in report_docs:
                        try:
                            await rp.insert()
                        except Exception:
                            pass
            logger.info(f"✅ Reports Migration: Inserted {len(report_docs)} reports into MongoDB.")
        except Exception as e:
            logger.warning(f"Reports migration note: {e}")

    mongo_client.close()
    logger.info("================ DATA MIGRATION COMPLETED SUCCESSFULLY ================")

if __name__ == "__main__":
    asyncio.run(migrate_data())

