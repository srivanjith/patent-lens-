import sys
import os
import json
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine, Base, ensure_columns_exist
from app.models.models import Patent
from ml.embedding_service import embedding_service
from ml.preprocessing import prepare_combined_text
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("patentlens.seed")

def seed_patents_if_needed(db: Session | None = None, force_reseed: bool = False):
    """Seed sample patent dataset and generate SBERT embeddings if database is missing patents."""
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        Base.metadata.create_all(bind=engine)
        ensure_columns_exist(engine)

        # Seed Demo User if missing
        try:
            from app.models.models import User
            from app.core.security import hash_password
        except ImportError:
            from app.models.models import User
            from app.core.security import hash_password

        demo_user = db.query(User).filter(User.email == "inventor@startup.com").first()
        if not demo_user:
            demo_user = User(
                name="Demo Inventor",
                email="inventor@startup.com",
                password_hash=hash_password("password123"),
                is_verified=True
            )
            db.add(demo_user)
            db.commit()
            logger.info("Demo user 'inventor@startup.com' created successfully.")
        
        json_path = os.path.join(os.path.dirname(__file__), "..", "data", "sample_patents.json")
        if not os.path.exists(json_path):
            logger.error(f"Sample patent data file not found at {json_path}")
            return

        with open(json_path, "r", encoding="utf-8") as f:
            patents_data = json.load(f)

        existing_patent_count = db.query(Patent).count()
        if existing_patent_count >= 10 and not force_reseed:
            logger.info(f"Database already populated with {existing_patent_count} sample patents. Skipping seeding.")
            return

        existing_patent_map = {p.patent_number: p for p in db.query(Patent).all()}
        missing_count = sum(1 for p in patents_data if p["patent_number"] not in existing_patent_map)
        if missing_count == 0 and not force_reseed:
            logger.info(f"Database fully seeded with all {len(patents_data)} sample patents. Skipping seeding.")
            return

        logger.info(f"Found {missing_count} missing sample patents (force={force_reseed}). Seeding into database & computing SBERT embeddings...")
        
        if not embedding_service.is_loaded:
            embedding_service.load_model()

        import uuid
        added = 0
        updated = 0
        for item in patents_data:
            existing = existing_patent_map.get(item["patent_number"])

            combined_text = prepare_combined_text(
                title=item["title"],
                problem_statement="",
                description=item["abstract"] + " " + item["description"]
            )
            embedding_vec = embedding_service.generate_embedding(combined_text)

            if existing:
                existing.patent_number = item["patent_number"]
                existing.title = item["title"]
                existing.abstract = item["abstract"]
                existing.description = item["description"]
                existing.domain = item["domain"]
                existing.inventors = item["inventors"]
                existing.assignee = item["assignee"]
                existing.publication_date = item["publication_date"]
                existing.source_url = item.get("source_url")
                existing.embedding = embedding_vec
                updated += 1
            else:
                patent = Patent(
                    id=item.get("id") or str(uuid.uuid4()),
                    patent_number=item["patent_number"],
                    title=item["title"],
                    abstract=item["abstract"],
                    description=item["description"],
                    inventors=item["inventors"],
                    assignee=item["assignee"],
                    publication_date=item["publication_date"],
                    domain=item["domain"],
                    source_url=item.get("source_url"),
                    source_type=item.get("source_type") or "DATABASE REPOSITORY",
                    source_status=item.get("source_status") or "DATABASE",
                    embedding=embedding_vec
                )
                db.add(patent)
                added += 1

        db.commit()
        logger.info(f"Successfully seeded {added} new patents and updated {updated} existing patents with 384-d SBERT embeddings.")

    except Exception as e:
        logger.error(f"Error during patent database seeding: {e}")
        db.rollback()
    finally:
        if close_session:
            db.close()

if __name__ == "__main__":
    seed_patents_if_needed(force_reseed=True)

