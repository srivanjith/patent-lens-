import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ["TESTING"] = "false"
os.environ["LIVE_BENCHMARK"] = "true"

from app.core.database import SessionLocal
from app.models.models import User, Patent
from app.schemas.schemas import PriorArtSearchRequest
from app.api.search import perform_prior_art_search

def run_debug_healthcare():
    print("Starting debug healthcare script...", flush=True)
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            print("No user found in DB, creating test user...", flush=True)
            from app.core.security import hash_password
            user = User(
                email="test_healthcare@patentlens.ai",
                password_hash=hash_password("TestPass123!"),
                name="Healthcare Tester",
                is_verified=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        print(f"User acquired: {user.email} (ID: {user.id})", flush=True)

        req = PriorArtSearchRequest(
            title="Wearable Healthcare Device for Physiological Monitoring and Vital Signs",
            domain="Healthcare",
            reference_date="2024-02-01",
            problem_statement="Continuous health monitoring requires non-invasive, low-power wearable devices capable of accurately capturing physiological parameters such as heart rate, blood oxygen saturation (SpO2), and pulse waveform in real time without causing skin irritation or draining battery quickly.",
            description="The wearable device incorporates an optical photoplethysmography (PPG) sensor, an electrocardiogram (ECG) sensor, and temperature sensors integrated into a flexible wristband. A low-power microcontroller receives raw physiological data, performs digital filtering to remove motion artifacts, and transmits encrypted telemetry over Bluetooth Low Energy to a mobile health platform. An embedded algorithm detects arrhythmia and abnormal pulse wave velocity, triggering emergency notifications to caregivers when vitals cross clinical thresholds.",
            keywords=[
                "wearable physiological sensor", "photoplethysmography", "PPG sensor",
                "ECG sensor", "vital signs monitoring", "heart rate variability",
                "blood oxygen saturation", "pulse wave velocity", "arrhythmia detection",
                "bluetooth low energy"
            ]
        )

        print("Executing perform_prior_art_search with wearable healthcare input...")
        response = perform_prior_art_search(request=req, current_user=user, db=db)
        print(f"\nSearch ID: {response.search_id}")
        print(f"Total Results: {len(response.results)}")
        pm = response.summary.pipeline_metrics if response.summary else None
        print(f"Pipeline Metrics:")
        print(f"  Patents Searched: {response.summary.patents_searched if response.summary else 'N/A'}")
        print(f"  API Retrieved: {pm.api_records_returned if pm else 'N/A'}")
        print(f"  Vector Shortlisted: {pm.vector_shortlisted_count if pm else 'N/A'}")
        print(f"  LLM Provider: {pm.active_llm_provider if pm else 'N/A'}")
        print(f"  LLM Model: {pm.active_llm_model if pm else 'N/A'}")

        print("\nTop 5 Results:")
        for idx, item in enumerate(response.results[:5], start=1):
            p = item.patent
            print(f"  Rank #{idx}: {p.patent_number} | {p.title} | Source: {p.source_type} ({item.source_status}) | Score: {item.final_score}%")

    finally:
        db.close()

if __name__ == "__main__":
    run_debug_healthcare()
