import os
import sys
import asyncio
import logging

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import settings
from app.models.models import UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("patentlens.verification")

async def verify_mongodb():
    logger.info("================ VERIFYING MONGODB ATLAS CONNECTION & DATA ================")
    
    mongo_url = getattr(settings, "MONGODB_URL", "")
    db_name = getattr(settings, "MONGODB_DB_NAME", "patentlens")
    
    logger.info(f"Target Database: {db_name}")
    
    client = AsyncIOMotorClient(mongo_url)
    await init_beanie(
        database=client[db_name],
        document_models=[UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc]
    )
    
    # 1. Check Document Counts
    user_count = await UserDoc.count()
    patent_count = await PatentDoc.count()
    search_count = await SearchDoc.count()
    saved_count = await SavedPatentDoc.count()
    report_count = await ReportDoc.count()
    
    logger.info("================ COLLECTION STATS ================")
    logger.info(f"  • Users Collection:        {user_count} documents")
    logger.info(f"  • Patents Collection:      {patent_count} documents")
    logger.info(f"  • Searches Collection:     {search_count} documents")
    logger.info(f"  • Saved Patents Collection:{saved_count} documents")
    logger.info(f"  • Reports Collection:      {report_count} documents")
    logger.info("==================================================")
    
    # 2. Sample Data Verification
    if user_count > 0:
        sample_user = await UserDoc.find_one()
        logger.info(f"Sample User: email='{sample_user.email}', name='{sample_user.name}', is_verified={sample_user.is_verified}")
    
    if patent_count > 0:
        sample_patent = await PatentDoc.find_one()
        logger.info(f"Sample Patent: number='{sample_patent.patent_number}', title='{sample_patent.title[:50]}...', domain='{sample_patent.domain}'")
    
    if search_count > 0:
        sample_search = await SearchDoc.find_one()
        logger.info(f"Sample Search: title='{sample_search.invention_title[:40]}...', results_count={len(sample_search.results)}, highest_sim={sample_search.highest_similarity}%")
    
    client.close()
    logger.info("================ MONGODB ATLAS VERIFICATION SUCCESSFUL ================")

if __name__ == "__main__":
    asyncio.run(verify_mongodb())
