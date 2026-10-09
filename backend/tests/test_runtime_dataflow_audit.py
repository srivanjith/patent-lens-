import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app
from ml.similarity_engine import compute_hybrid_score, calculate_deterministic_final_score

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
                name="Audit User",
                email="audit@patentlens.ai",
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


def test_lens_http_200_zero_records():
    """Test HTTP 200 with 0 records produces status LENS_NO_RESULTS."""
    from app.services.lens_api_service import LensAPIService
    service = LensAPIService()

    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {"data": []}

    with patch("httpx.Client.post", return_value=mock_res):
        res = service.search_patents(["battery management system"])
        assert res["status"] == "LENS_NO_RESULTS"
        assert res["retrieved_count"] == 0


def test_lens_http_429_rate_limited():
    """Test HTTP 429 produces status LENS_RATE_LIMITED."""
    from app.services.lens_api_service import LensAPIService
    service = LensAPIService()

    mock_res = MagicMock()
    mock_res.status_code = 429
    mock_res.text = "Too Many Requests"

    with patch("httpx.Client.post", return_value=mock_res):
        res = service.search_patents(["network security intrusion"])
        assert res["status"] == "LENS_RATE_LIMITED"
        assert res["retrieved_count"] == 0


def test_lens_http_401_403_auth_error():
    """Test HTTP 401/403 produces status LENS_AUTH_ERROR."""
    from app.services.lens_api_service import LensAPIService
    service = LensAPIService()

    mock_res = MagicMock()
    mock_res.status_code = 401
    mock_res.text = "Unauthorized Token"

    with patch("httpx.Client.post", return_value=mock_res):
        res = service.search_patents(["solar panel cleaning"])
        assert res["status"] == "LENS_AUTH_ERROR"
        assert res["retrieved_count"] == 0


def test_database_fallback_provenance():
    """Test database fallback candidates explicitly preserve DATABASE source provenance."""
    payload = {
        "title": "AI-Based Network Intrusion Detection System",
        "domain": "Software / Cybersecurity",
        "problem_statement": "Undetected network anomalies",
        "description": "Deep neural network traffic monitoring",
        "keywords": ["cybersecurity"]
    }
    from app.services.lens_api_service import lens_api_service
    from app.services.patent_api_service import patent_api_service
    with patch.object(lens_api_service, "search_patents") as mock_lens, \
         patch.object(patent_api_service, "fetch_and_cache_external_patents") as mock_pat:
        mock_lens.return_value = {"results": [], "status": "LENS_RATE_LIMITED", "retrieved_count": 0}
        mock_pat.return_value = {"patents_retrieved": 0, "patents_searched": 0, "lens_api_status": "LENS_RATE_LIMITED"}
        res = client.post("/api/search", json=payload)
        assert res.status_code == 201
        data = res.json()
        
        summary = data["summary"]
        pipeline = summary["pipeline_metrics"]
        
        assert pipeline["patents_retrieved"] == 0
        assert pipeline["lens_records_retrieved"] == 0
        assert pipeline["database_fallback_candidates"] > 0
        assert pipeline["lens_api_status"] == "LENS_RATE_LIMITED"

        for item in data["results"]:
            assert item["source_status"] == "DATABASE"
            assert item["source_name"] == "Database Repository"
            assert item["retrieval_status"] in ["DATABASE_REPOSITORY", "DATABASE_REPOSITORY_FALLBACK"]


def test_zero_evidence_confidence_bounded():
    """Test zero verified evidence yields confidence between 10.0% and 25.0%."""
    final_score, conf_score, breakdown = calculate_deterministic_final_score(
        sbert_sim=0.40,
        feature_score=0.20,
        evidence_strength=0.0,
        distinctive_score=0.0,
        domain_cpc_score=0.50,
        technology_domain_score=0.50,
        cpc_match_score=0.40,
        has_target_features=True,
        essential_feature_coverage=0.0,
        has_text_evidence=False
    )
    assert 10.0 <= conf_score <= 25.0


def test_abstract_title_only_partial_match_status():
    """Test abstract/title only produces feature_match_status=PARTIAL and source=ABSTRACT/TITLE."""
    patent_dict = {
        "title": "Network Threat Detection Apparatus",
        "abstract": "Discloses monitoring network packet headers for zero-day threat anomalies.",
        "description": "",
        "claims": "",
        "domain": "Software / Cybersecurity"
    }
    user_emb = [0.1] * 384
    pat_emb = [0.1] * 384
    
    sc = compute_hybrid_score(
        user_embedding=user_emb,
        patent_embedding=pat_emb,
        user_keywords=["cybersecurity"],
        user_concepts=["network intrusion"],
        user_domain="Software / Cybersecurity",
        patent=patent_dict,
        target_text_for_concepts="AI network intrusion detection threat response",
        technical_features=["network intrusion detection", "threat response"]
    )
    assert sc["feature_match_status"] == "PARTIAL"
    assert sc["feature_match_source"] == "ABSTRACT"


def test_claims_description_verified_source():
    """Test full specification claims/description text produces CLAIMS/DESCRIPTION feature match source."""
    patent_dict = {
        "title": "Network Threat Detection System",
        "abstract": "Discloses network intrusion detection.",
        "description": "Comprehensive specification describing neural network packet monitoring and automated firewall rule generation.",
        "claims": "1. A network intrusion detection system comprising deep neural network packet analysis.",
        "domain": "Software / Cybersecurity"
    }
    user_emb = [0.1] * 384
    pat_emb = [0.1] * 384
    
    sc = compute_hybrid_score(
        user_embedding=user_emb,
        patent_embedding=pat_emb,
        user_keywords=["cybersecurity"],
        user_concepts=["network intrusion"],
        user_domain="Software / Cybersecurity",
        patent=patent_dict,
        target_text_for_concepts="AI network intrusion detection threat response",
        technical_features=["network intrusion detection", "threat response"]
    )
    assert sc["feature_match_source"] == "CLAIMS/DESCRIPTION"


def test_family_deduplication_metrics():
    """Test family deduplication metric consistency across raw, family IDs, unique families, and post-dedup."""
    payload = {
        "title": "Smart Water Leak Detection System Using IoT Sensors",
        "domain": "IoT / Environmental Monitoring",
        "problem_statement": "Undetected pipe burst water leakage",
        "description": "A smart plumbing monitoring system comprising acoustic vibration sensors and flow rate meters.",
        "keywords": ["IoT", "water leak"]
    }
    res = client.post("/api/search", json=payload)
    assert res.status_code == 201
    data = res.json()
    summary = data["summary"]
    pipeline = summary["pipeline_metrics"]

    assert pipeline["unique_families"] == summary["unique_families_count"]
    assert pipeline["raw_candidates"] > 0
    assert pipeline["post_dedup_candidates"] == pipeline["unique_families"]


def test_frontend_backend_field_consistency():
    """Test frontend-required backend response fields are fully consistent and present."""
    payload = {
        "title": "Autonomous Warehouse Inventory Robot",
        "domain": "Robotics / Automation",
        "problem_statement": "Labor-intensive manual warehouse stocktaking",
        "description": "Autonomous mobile robot featuring 3D LiDAR spatial mapping and optical barcode scanning.",
        "keywords": ["robotics"]
    }
    res = client.post("/api/search", json=payload)
    assert res.status_code == 201
    data = res.json()
    
    for item in data["results"]:
        assert item["total_feature_count"] >= 1
        assert "matched_feature_count" in item
        assert "feature_match_status" in item
        assert "feature_match_source" in item
        assert item["source_status"] in ["LIVE_API", "DATABASE"]
        assert item["source_name"] in ["The Lens Patent API", "Database Repository"]
        assert item["retrieval_status"] in ["LIVE_API_SUCCESS", "DATABASE_REPOSITORY_FALLBACK", "DATABASE_REPOSITORY"]
        
        # Verify confidence <= 25% when evidence is unverified
        if item.get("verification_status") != "VERIFIED" and not any(e.get("verified") for e in item.get("evidence_items", [])):
            assert item["confidence_score"] <= 25.0
            assert item["evidence_confidence"] <= 25.0
            assert item["confidence_score"] >= 10.0
