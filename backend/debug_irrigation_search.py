import os
import sys
import asyncio

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["TESTING"] = "false"
os.environ["LIVE_BENCHMARK"] = "true"

from app.core.database import SessionLocal
from app.models.models import User, Patent
from app.schemas.schemas import PriorArtSearchRequest
from app.api.search import perform_prior_art_search

async def run_debug():
    print("Starting debug script...", flush=True)
    db = SessionLocal()
    try:
        print("Querying user...", flush=True)
        user = db.query(User).first()
        if not user:
            print("No user found in DB, creating test user...", flush=True)
            from app.core.security import hash_password
            user = User(
                email="test_irrigation@patentlens.ai",
                password_hash=hash_password("TestPass123!"),
                name="Irrigation Tester",
                is_verified=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        print(f"User acquired: {user.email} (ID: {user.id})", flush=True)
            
        req = PriorArtSearchRequest(
            title="AI-Based Smart Irrigation System Using Soil Moisture and Weather Prediction",
            domain="Artificial Intelligence",
            reference_date="2024-01-15",
            problem_statement="Conventional irrigation systems use fixed watering schedules and often waste water because they do not respond to changing soil moisture, rainfall, or weather conditions. Small-scale farmers also lack affordable systems that can predict irrigation requirements and automatically control water delivery.",
            description="The system uses soil-moisture sensors, temperature and humidity sensors, and weather forecast data to estimate crop water requirements. A machine-learning model combines current sensor readings with historical irrigation and weather data to predict soil-moisture levels over the next several hours. A microcontroller activates a water pump or solenoid valve when the predicted moisture level falls below a crop-specific threshold. The controller delays irrigation when rainfall is forecast, records water consumption, and sends alerts to a farmer through a mobile application. The system supports adjustable thresholds for different crops and low-cost hardware for small farms.",
            keywords=[
                "soil moisture sensor", "predictive irrigation", "machine learning",
                "weather forecasting", "rainfall prediction", "automated water pump",
                "solenoid valve", "microcontroller", "crop-specific threshold", "water conservation"
            ]
        )
        
        print("Executing perform_prior_art_search with exact irrigation input...")
        response = await perform_prior_art_search(request=req, current_user=user, db=db)
        print(f"\nSearch ID: {response.search_id}")
        print(f"Total Results: {len(response.results)}")
        print(f"Summary: {response.summary.model_dump() if response.summary else 'None'}")
        
        for idx, item in enumerate(response.results, start=1):
            p = item.patent
            bd = item.score_breakdown
            tf_bd = bd.technical_features if bd else None
            print("\n" + "-" * 50)
            print(f"Rank #{idx}: {p.patent_number} | {p.title}")
            print(f"  Final Score: {item.final_score}%")
            print(f"  Semantic Score: {item.semantic_score}%")
            print(f"  Keyword Score: {item.keyword_score}%")
            print(f"  Matched Feature Count: {item.matched_feature_count}")
            print(f"  Total Feature Count: {item.total_feature_count}")
            print(f"  Strong Matches: {item.strong_matches}")
            print(f"  Partial Matches: {item.partial_matches}")
            print(f"  Missing Features: {item.missing_features}")
            print(f"  Relevance Level: {item.relevance_level}")
            print(f"  Semantic Sim Label: {item.semantic_similarity_label}")
            print(f"  Evidence Status: {item.evidence_status} | Label: {item.evidence_status_label}")
            if tf_bd:
                print(f"  BD Technical Features Value: {tf_bd.value} | Status: {tf_bd.status} | Contrib: {tf_bd.contribution}")
            if item.evidence_items:
                print(f"  Evidence Items Count: {len(item.evidence_items)}")
                for ev in item.evidence_items[:2]:
                    print(f"    Ev: feat='{ev.feature}' status='{ev.status}' verified={ev.verified} quote='{ev.evidence[:40]}...'")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_debug())
