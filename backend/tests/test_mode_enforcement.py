import os
import sys
import subprocess
import pytest
from fastapi.testclient import TestClient
from main import app
from app.core.config import settings, BASE_DIR
from app.services.groq_service import groq_service
from app.services.gemini_service import gemini_service
from app.services.lens_api_service import lens_api_service
from app.services.patent_api_service import patent_api_service

from app.core.security import get_current_user
from app.models.models import User

async def mock_user():
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            user = User(
                id="test-user-id-1",
                name="Test User",
                email="test@patentlens.ai",
                password_hash="hashed_test_password",
                is_verified=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()

@pytest.fixture(autouse=True)
def override_user_dep():
    app.dependency_overrides[get_current_user] = mock_user
    yield
    app.dependency_overrides.clear()

client = TestClient(app)

def test_testing_mode_prevents_external_calls():
    """Verify TESTING=true prevents external LLM and Lens/arXiv API network calls."""
    os.environ["TESTING"] = "true"
    settings.TESTING = True

    arxiv_recs = patent_api_service._fetch_from_arxiv("solar panel", ["solar"], "CleanTech")
    assert arxiv_recs == []

    pv_recs = patent_api_service._fetch_from_patentsview("solar panel", ["solar"], "CleanTech")
    assert pv_recs == []

def test_testing_false_preserves_production_configuration():
    """Verify TESTING=false preserves actual production service configurations."""
    os.environ["TESTING"] = "false"
    settings.TESTING = False

    # Check that settings configuration is intact
    if settings.GROQ_API_KEY and not settings.GROQ_API_KEY.startswith("your_"):
        assert groq_service.is_configured is True
    if settings.LENS_API_TOKEN and not settings.LENS_API_TOKEN.startswith("your_"):
        assert lens_api_service.is_configured is True

    # Re-enable TESTING=true for subsequent tests
    os.environ["TESTING"] = "true"
    settings.TESTING = True

def test_live_benchmark_requires_explicit_opt_in():
    """Verify run_live_10_domain_benchmark.py aborts when LIVE_BENCHMARK=true is missing."""
    env = os.environ.copy()
    env["LIVE_BENCHMARK"] = "false"
    root_dir = BASE_DIR.parent
    env["PYTHONPATH"] = str(root_dir)

    cmd = [sys.executable, "backend/scripts/run_live_10_domain_benchmark.py"]
    res = subprocess.run(cmd, cwd=root_dir, env=env, capture_output=True, text=True)

    assert res.returncode != 0
    assert "ABORTED: LIVE 10-DOMAIN AUDIT BENCHMARK IS NOT ENABLED" in res.stdout or "ABORTED" in res.stderr or "ABORTED" in res.stdout

def test_fixture_provenance_cannot_be_reported_as_live_api():
    """Verify test fixtures and regression searches never claim LIVE_API provenance."""
    os.environ["TESTING"] = "true"
    settings.TESTING = True

    payload = {
        "title": "Smart Water Leak Detection System",
        "domain": "IoT / Environmental",
        "problem_statement": "Undetected water leakages",
        "description": "Smart plumbing system with ultrasonic sensors",
        "keywords": ["IoT"]
    }

    res = client.post("/api/search", json=payload)
    assert res.status_code == 201
    data = res.json()

    assert "Live API" not in data.get("data_source", "")
    results = data.get("results", [])
    if results:
        assert results[0].get("source_status") in ["DATABASE", "CACHE", "FALLBACK", "TEST_FIXTURE"]
        assert results[0].get("source_status") != "LIVE_API"
