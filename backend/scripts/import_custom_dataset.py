import sys
import os
import json
import csv
import time
import logging
from typing import List, Dict, Any, Callable, TypeVar

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, engine, ensure_columns_exist
from app.models.models import Patent
from ml.embedding_service import embedding_service
from ml.preprocessing import prepare_combined_text
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("patentlens.import_custom")

T = TypeVar("T")

def load_records_from_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse custom dataset from JSON, CSV, or JSONL file formats.
    """
    if not os.path.exists(file_path):
        logger.error(f"Dataset file not found at: {file_path}")
        return []

    ext = os.path.splitext(file_path)[1].lower()
    records = []

    try:
        if ext == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                records = content if isinstance(content, list) else content.get("patents", [content])
        elif ext == ".jsonl":
            with open(file_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
        elif ext == ".csv":
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                records = list(reader)
        else:
            logger.error(f"Unsupported file extension: '{ext}'. Use .json, .csv, or .jsonl")
            return []

        logger.info(f"Loaded {len(records)} raw records from {file_path}")
        return records

    except Exception as e:
        logger.error(f"Failed to parse dataset file {file_path}: {e}")
        return []


def execute_with_db_retry(operation_func: Callable[[Any], T], max_retries: int = 3) -> T:
    """
    Execute a database operation with automatic engine disposal and reconnection 
    if Neon / PostgreSQL closes an idle connection unexpectedly.
    """
    last_exception = None
    for attempt in range(1, max_retries + 1):
        db = SessionLocal()
        try:
            result = operation_func(db)
            db.close()
            return result
        except Exception as e:
            last_exception = e
            db.rollback()
            db.close()
            err_msg = str(e).lower()
            is_conn_error = any(kw in err_msg for kw in [
                "server closed the connection",
                "operationalerror",
                "connection refusal",
                "ssl connection has been closed",
                "socket",
                "terminated unexpectedly"
            ])
            if is_conn_error and attempt < max_retries:
                logger.warning(f"[NEON RECONNECT] Connection closed unexpectedly (Attempt {attempt}/{max_retries}): {e}. Disposing engine pool and reconnecting...")
                engine.dispose()
                time.sleep(2 * attempt)
            else:
                if attempt >= max_retries:
                    logger.error(f"Database operation failed after {max_retries} attempts: {e}")
                raise e

    if last_exception:
        raise last_exception
    raise RuntimeError("Database operation failed without returning a result.")


def import_custom_dataset_to_postgres(file_path: str, default_domain: str = "Artificial Intelligence"):
    """
    Import patent dataset (e.g., google_patents_10000_cleaned.csv) into PostgreSQL database.

    SAFETY & CONNECTION STABILITY INTEGRITY:
    1. Uses ensure_columns_exist(engine) instead of redundant Base.metadata.create_all().
    2. Does NOT delete, truncate, overwrite, or reclassify existing Lens or existing database records.
    3. Skips records whose publication_number/patent_number already exists in the database.
    4. Preserves genuine missing values as NULL/empty string without inventing fake metadata.
    5. Sets source_type = 'GOOGLE PATENTS', source_status = 'LIVE_DATASET', document_type = 'PATENT'.
    6. Employs batch processing (size 50) and engine reconnection safety to handle Neon idle timeouts.
    """
    records = load_records_from_file(file_path)
    if not records:
        logger.warning("No records loaded to import.")
        return

    # Schema column verification without heavy create_all metadata locks
    try:
        ensure_columns_exist(engine)
    except Exception as e:
        logger.warning(f"Schema column check note: {e}")

    if not embedding_service.is_loaded:
        logger.info("Initializing SBERT embedding model...")
        embedding_service.load_model()

    # Fetch all existing patent numbers with safe connection retry
    def _fetch_existing(session):
        existing_nums = set(row[0] for row in session.query(Patent.patent_number).all())
        lens_cnt = session.query(Patent).filter(Patent.source_type == "THE LENS").count()
        return existing_nums, lens_cnt

    existing_numbers, existing_lens_count = execute_with_db_retry(_fetch_existing)
    initial_db_count = len(existing_numbers)

    logger.info(f"Existing database count: {initial_db_count} records (Protected Lens records: {existing_lens_count})")
    logger.info(f"Starting resilient batch import of {len(records)} candidate records...")

    loaded_count = len(records)
    inserted_count = 0
    skipped_count = 0
    failed_count = 0
    batch_size = 50

    for i in range(0, loaded_count, batch_size):
        batch_raw = records[i : i + batch_size]
        batch_to_insert = []
        texts_to_embed = []

        for index, item in enumerate(batch_raw):
            pat_num = (
                item.get("publication_number")
                or item.get("patent_number")
                or item.get("patent_id")
                or item.get("id")
                or ""
            ).strip()

            if not pat_num:
                failed_count += 1
                continue

            if pat_num in existing_numbers:
                skipped_count += 1
                continue

            title = (item.get("title") or item.get("patent_title") or "").strip()
            abstract = (item.get("abstract") or item.get("patent_abstract") or title).strip()
            description = (
                item.get("publication_description")
                or item.get("patent_text")
                or item.get("description")
                or item.get("patent_description")
                or abstract
            ).strip()

            if not title or not abstract:
                failed_count += 1
                continue

            inventors = (item.get("inventors") or item.get("inventor") or "").strip()
            assignee = (item.get("assignee") or item.get("organization") or item.get("applicant") or "").strip()
            pub_date = str(item.get("publication_date") or item.get("date") or "").strip()
            domain = (item.get("domain") or default_domain).strip()
            
            source_url = (item.get("source_url") or item.get("url") or f"https://patents.google.com/patent/{pat_num}/en").strip()
            claims = item.get("claims") or None
            if claims:
                claims = str(claims).strip() or None

            cpc_codes = item.get("cpc") or item.get("cpc_codes") or None
            if cpc_codes:
                cpc_codes = str(cpc_codes).strip() or None

            ipc_codes = item.get("ipc") or item.get("ipc_codes") or None
            if ipc_codes:
                ipc_codes = str(ipc_codes).strip() or None

            combined_text = prepare_combined_text(title=title, problem_statement="", description=abstract + " " + description[:300])

            batch_to_insert.append({
                "pat_num": pat_num,
                "title": title,
                "abstract": abstract,
                "description": description,
                "inventors": inventors,
                "assignee": assignee,
                "publication_date": pub_date,
                "domain": domain,
                "source_url": source_url,
                "claims": claims,
                "cpc_codes": cpc_codes,
                "ipc_codes": ipc_codes,
                "filing_date": item.get("filing_date") or None,
                "earliest_priority_date": item.get("earliest_priority_date") or None,
                "simple_family_id": item.get("simple_family_id") or None,
            })
            texts_to_embed.append(combined_text)

        if batch_to_insert:
            try:
                embeddings = embedding_service.generate_embeddings(texts_to_embed)

                def _insert_batch_op(session):
                    for item_dict, emb_vec in zip(batch_to_insert, embeddings):
                        patent = Patent(
                            patent_number=item_dict["pat_num"],
                            title=item_dict["title"],
                            abstract=item_dict["abstract"],
                            description=item_dict["description"],
                            inventors=item_dict["inventors"],
                            assignee=item_dict["assignee"],
                            publication_date=item_dict["publication_date"],
                            domain=item_dict["domain"],
                            source_url=item_dict["source_url"],
                            claims=item_dict["claims"],
                            cpc_codes=item_dict["cpc_codes"],
                            ipc_codes=item_dict["ipc_codes"],
                            filing_date=item_dict["filing_date"],
                            earliest_priority_date=item_dict["earliest_priority_date"],
                            simple_family_id=item_dict["simple_family_id"],
                            source_type="GOOGLE PATENTS",
                            source_status="LIVE_DATASET",
                            document_type="PATENT",
                            embedding=emb_vec
                        )
                        session.add(patent)
                    session.commit()

                execute_with_db_retry(_insert_batch_op)
                for item_dict in batch_to_insert:
                    existing_numbers.add(item_dict["pat_num"])
                inserted_count += len(batch_to_insert)

            except Exception as batch_err:
                logger.error(f"Failed to insert batch starting at index {i}: {batch_err}")
                failed_count += len(batch_to_insert)

        processed = min(i + batch_size, loaded_count)
        logger.info(f"Progress: {processed}/{loaded_count} processed | Inserted: {inserted_count} | Skipped: {skipped_count} | Failed: {failed_count}")

    def _fetch_final_counts(session):
        final_lens = session.query(Patent).filter(Patent.source_type == "THE LENS").count()
        total_db = session.query(Patent).count()
        return final_lens, total_db

    final_lens_count, total_db_count = execute_with_db_retry(_fetch_final_counts)

    logger.info("================ IMPORT SUMMARY ================")
    logger.info(f"Total Loaded Records:    {loaded_count}")
    logger.info(f"Successfully Inserted:   {inserted_count}")
    logger.info(f"Skipped (Already Exists):{skipped_count}")
    logger.info(f"Failed Records:          {failed_count}")
    logger.info(f"Protected Lens Records:  {final_lens_count} (Unchanged)")
    logger.info(f"Total DB Records Now:    {total_db_count}")
    logger.info("================================================")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backend.scripts.import_custom_dataset <path_to_dataset_file> [default_domain]")
        print("Example: python -m backend.scripts.import_custom_dataset google_patents_10000_cleaned.csv \"Artificial Intelligence\"")
        sys.exit(1)

    dataset_path = sys.argv[1]
    domain_arg = sys.argv[2] if len(sys.argv) > 2 else "Artificial Intelligence"
    import_custom_dataset_to_postgres(file_path=dataset_path, default_domain=domain_arg)
