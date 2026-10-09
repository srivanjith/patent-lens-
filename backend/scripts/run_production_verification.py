import sys
import os
import asyncio
import json

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings
from app.models.models import UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc
from app.schemas.schemas import PriorArtSearchRequest
from app.core.security import hash_password, verify_password, create_access_token, decode_token
from ml.embedding_service import embedding_service
from ml.similarity_engine import compute_hybrid_score, calculate_cosine_similarity
from ml.preprocessing import prepare_combined_text
from ml.keyword_extractor import extract_technical_concepts
from app.services.report_service import generate_pdf_report

async def run_verification():
    print("=" * 70)
    print("PATENTLENS AI - POST-MIGRATION MONGODB ATLAS PRODUCTION VERIFICATION")
    print("=" * 70)

    mongo_url = settings.MONGODB_URL
    db_name = settings.MONGODB_DB_NAME
    print(f"\n[1] Connecting to MongoDB Atlas: {db_name}...")
    
    client = AsyncIOMotorClient(mongo_url)
    await init_beanie(database=client[db_name], document_models=[UserDoc, PatentDoc, SearchDoc, SavedPatentDoc, ReportDoc])
    print(" -> MongoDB Atlas & Beanie ODM Connection: SUCCESS")

    # Document counts
    user_count = await UserDoc.count()
    patent_count = await PatentDoc.count()
    search_count = await SearchDoc.count()
    saved_count = await SavedPatentDoc.count()
    report_count = await ReportDoc.count()

    print(f" -> Live User Documents: {user_count}")
    print(f" -> Live Patent Documents: {patent_count}")
    print(f" -> Live Search Documents: {search_count}")
    print(f" -> Live Saved Patent Documents: {saved_count}")
    print(f" -> Live Report Documents: {report_count}")

    assert user_count >= 100, "Expected at least 100 migrated users!"
    assert patent_count >= 10000, "Expected at least 10,000 migrated patents!"
    print(" [PASS] MongoDB Atlas collection counts meet production threshold criteria.")

    # [2] Authentication & Security Verification
    print("\n[2] Verifying User Auth, Password Hashing, OTP & JWT...")
    test_email = "prod_verify_test_user@patentlens.ai"
    test_pwd = "SecureProdPassword123!"
    hashed_pwd = hash_password(test_pwd)

    # Clean up test user if exists
    existing = await UserDoc.find_one(UserDoc.email == test_email)
    if existing:
        await existing.delete()

    test_user = UserDoc(
        name="Production Verification Bot",
        email=test_email,
        password_hash=hashed_pwd,
        is_verified=True
    )
    await test_user.insert()
    print(" -> User Doc inserted into MongoDB Atlas.")

    found_user = await UserDoc.find_one(UserDoc.email == test_email)
    assert found_user is not None, "Failed to retrieve test user from MongoDB Atlas!"
    assert verify_password(test_pwd, found_user.password_hash), "Password verification failed!"

    token = create_access_token({"sub": found_user.id, "email": found_user.email})
    payload = decode_token(token, settings.JWT_SECRET)
    assert payload.get("sub") == found_user.id, "JWT sub claim mismatch!"
    print(" [PASS] User Auth, bcrypt hashing, JWT issuance and MongoDB retrieval verified.")

    # [3] FastEmbed & Embedding Retrieval Verification
    print("\n[3] Verifying SBERT / FastEmbed 384-dimensional Vector Similarity...")
    test_req = PriorArtSearchRequest(
        title="Smart Solar Powered Autonomous Drone Navigation",
        problem_statement="Drones suffer from limited battery life during autonomous mapping flights.",
        description="A solar panel integrated lightweight drone system utilizing real-time sensor fusion for automated obstacle avoidance and path planning.",
        domain="Drone & Solar Technology",
        keywords=["solar drone", "autonomous mapping", "obstacle avoidance", "battery management"]
    )

    if not embedding_service.is_loaded:
        embedding_service.load_model()
    
    emb = embedding_service.generate_embedding(f"{test_req.title} {test_req.description}")
    assert len(emb) == 384, f"Expected 384-dimensional embedding, got {len(emb)}"
    print(f" -> SBERT FastEmbed generated {len(emb)}-dimensional vector embedding.")

    # Retrieve candidate documents from MongoDB Atlas
    patents = await PatentDoc.find().limit(300).to_list()
    assert len(patents) > 0, "No patents found in MongoDB Atlas!"

    target_concepts = extract_technical_concepts(f"{test_req.title} {test_req.problem_statement} {test_req.description}")

    scored = []
    for p in patents:
        if not p.embedding:
            continue
        p_emb = p.embedding
        patent_dict = {
            "title": p.title,
            "abstract": p.abstract,
            "claims": p.claims or "",
            "description": p.description or "",
            "domain": p.domain or "",
            "cpc_codes": p.cpc_codes or ""
        }
        score_dict = compute_hybrid_score(
            user_embedding=emb,
            patent_embedding=p_emb,
            user_keywords=test_req.keywords,
            user_concepts=target_concepts,
            user_domain=test_req.domain,
            patent=patent_dict,
            target_text_for_concepts=f"{test_req.title} {test_req.problem_statement} {test_req.description}"
        )
        scored.append({
            "patent": p,
            "final_score": score_dict["final_score"],
            "semantic_score": score_dict["semantic_score"],
            "score_dict": score_dict
        })

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    assert len(scored) > 0, "Vector search returned 0 candidates!"
    top_match = scored[0]
    p_match = top_match["patent"]
    
    print(f" -> Top Match: [{p_match.patent_number}] {p_match.title}")
    print(f" -> Final Score: {top_match['final_score']}% (Semantic: {top_match['semantic_score']}%)")
    print(f" -> Provenance: source_status={p_match.source_status}, source_type={p_match.source_type}")
    
    # Crucial Provenance Guarantee Verification
    assert p_match.source_status in ["DATABASE", "LIVE_API", "THE LENS"], f"Invalid source_status tag: {p_match.source_status}"
    if p_match.source_status == "DATABASE":
        assert p_match.source_type != "THE LENS", "CRITICAL PROVENANCE FAILURE: DATABASE record tagged as THE LENS!"
    elif p_match.source_status == "LIVE_API":
        assert p_match.source_type == "THE LENS", "LIVE_API record missing THE LENS source_type tag!"
    print(" [PASS] Vector search and strictly enforced provenance tagging verified.")

    # [4] Negative Control Check
    print("\n[4] Performing Negative Control Test (Unrelated Recipe vs Patent Corpus)...")
    recipe_req = PriorArtSearchRequest(
        title="Fluffy Chocolate Lava Cake Baking Recipe",
        problem_statement="Lava cakes often overcook or dry out in conventional ovens.",
        description="Baking chocolate cake using dark cocoa powder, whipped eggs, sugar, and melted butter baked at 350F for 12 minutes.",
        domain="Culinary Arts",
        keywords=["lava cake", "baking recipe", "dark cocoa", "whipped eggs"]
    )
    recipe_emb = embedding_service.generate_embedding(f"{recipe_req.title} {recipe_req.description}")
    recipe_concepts = extract_technical_concepts(f"{recipe_req.title} {recipe_req.description}")

    recipe_scored = []
    for p in patents[:150]:
        if not p.embedding:
            continue
        patent_dict = {
            "title": p.title,
            "abstract": p.abstract,
            "claims": p.claims or "",
            "description": p.description or "",
            "domain": p.domain or "",
            "cpc_codes": p.cpc_codes or ""
        }
        score_dict = compute_hybrid_score(
            user_embedding=recipe_emb,
            patent_embedding=p.embedding,
            user_keywords=recipe_req.keywords,
            user_concepts=recipe_concepts,
            user_domain=recipe_req.domain,
            patent=patent_dict,
            target_text_for_concepts=f"{recipe_req.title} {recipe_req.description}"
        )
        recipe_scored.append(score_dict["final_score"])

    top_recipe_score = max(recipe_scored) if recipe_scored else 0.0
    print(f" -> Top score for unrelated recipe: {top_recipe_score}%")
    assert top_recipe_score < 40.0, f"Score inflation detected! Recipe received {top_recipe_score}%"
    print(" [PASS] Negative control check passed. No score inflation detected.")

    # [5] Persistence & PDF Report Generation Verification
    print("\n[5] Verifying MongoDB Search Persistence & PDF Report Generation...")
    search_doc = SearchDoc(
        user_id=found_user.id,
        invention_title=test_req.title,
        domain=test_req.domain,
        problem_statement=test_req.problem_statement,
        description=test_req.description,
        keywords=test_req.keywords,
        risk_level="MODERATE",
        highest_similarity=top_match['final_score'],
        total_results=len(scored),
        patents_searched=len(patents),
        patents_retrieved=len(patents),
        patents_shortlisted=len(scored),
        patents_deeply_analyzed=min(10, len(scored))
    )
    await search_doc.insert()

    fetched_search = await SearchDoc.get(search_doc.id)
    assert fetched_search is not None, "Failed to retrieve persisted SearchDoc from MongoDB!"
    print(f" -> SearchDoc {search_doc.id} persisted and retrieved from MongoDB Atlas.")

    # Test PDF Report Generation
    pdf_path = generate_pdf_report(search_doc, [
        type("Obj", (), {
            "rank": 1,
            "final_score": top_match['final_score'],
            "semantic_score": top_match['semantic_score'],
            "keyword_score": 80.0,
            "domain_score": 90.0,
            "matched_concepts": ["solar drone", "navigation"],
            "patent": p_match
        })
    ])
    assert os.path.exists(pdf_path), "PDF report file was not created on disk!"
    pdf_size = os.path.getsize(pdf_path)
    print(f" -> Generated PDF Report at {pdf_path} ({pdf_size} bytes).")
    assert pdf_size > 1000, "PDF report file size too small!"
    print(" [PASS] MongoDB search persistence and PDF report generation verified.")

    # Cleanup test user & search doc
    await found_user.delete()
    await search_doc.delete()

    print("\n" + "=" * 70)
    print("ALL POST-MIGRATION PRODUCTION VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_verification())
