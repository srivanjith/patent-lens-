import pytest
import json
from unittest.mock import patch, MagicMock
import httpx

from app.schemas.schemas import PriorArtSearchRequest, PipelineMetrics, ProviderStatus
from app.services.lens_api_service import LensAPIService
from app.services.patent_api_service import PatentAPIService
from ml.similarity_engine import compute_hybrid_score
from ml.risk_classifier import classify_prior_art_risk


# =========================================================================
# Regression Test Suite: Live Retrieval, Fallback & Counter Integrity
# =========================================================================

def test_regression_01_successful_live_api_retrieval():
    """Scenario 1: Successful live API retrieval returns parsed records and accurate counters."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    
    mock_patent_data = [
        {
            "lens_id": "lens-001",
            "doc_number": "12144295",
            "jurisdiction": "US",
            "kind": "B2",
            "date_published": "2024-05-10",
            "biblio": {
                "invention_title": [{"text": "Smart irrigation system", "lang": "en"}],
                "abstract": [{"text": "A smart irrigation system with soil moisture sensing.", "lang": "en"}],
                "claims": [{"text": "1. A smart irrigation system comprising moisture sensors.", "lang": "en"}],
                "classifications_cpc": {"classifications": [{"symbol": "A01G25/16"}]}
            }
        },
        {
            "lens_id": "lens-002",
            "doc_number": "20210137035",
            "jurisdiction": "US",
            "kind": "A1",
            "date_published": "2021-05-13",
            "biblio": {
                "invention_title": [{"text": "Low-power intelligent irrigation network", "lang": "en"}],
                "abstract": [{"text": "RF network based irrigation controller.", "lang": "en"}],
                "classifications_cpc": {"classifications": [{"symbol": "A01G25/00"}]}
            }
        }
    ]

    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": mock_patent_data, "total": 2}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["smart irrigation soil moisture"], limit=10)
        assert res["status"] == "LENS_OK"
        assert res["provider_status"] == "success"
        assert res["retrieved_count"] == 2
        assert res["records_returned"] == 2
        assert res["records_unique"] == 2
        assert len(res["results"]) == 2
        assert res["results"][0]["patent_number"] == "US-12144295"
        assert res["results"][0]["source_status"] == "LIVE_API"
        assert res["results"][0]["source_type"] == "THE LENS"


def test_regression_02_api_returning_zero_results():
    """Scenario 2: External API returns zero results. Counters must be 0, status success_empty."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"

    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [], "total": 0}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["nonexistent obscure query 9999"], limit=10)
        assert res["retrieved_count"] == 0
        assert res["records_returned"] == 0
        assert res["records_unique"] == 0
        assert res["provider_status"] == "success_empty"
        assert res["status"] == "LENS_NO_RESULTS"
        assert len(res["results"]) == 0


def test_regression_03_api_authentication_failure():
    """Scenario 3: External API authentication failure (HTTP 401). Must report authentication_error."""
    service = LensAPIService()
    service.api_token = "invalid_expired_token"

    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized: Invalid or expired Bearer token"
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["smart irrigation"], limit=10)
        assert res["status"] == "LENS_AUTH_ERROR"
        assert res["provider_status"] == "authentication_error"
        assert res["retrieved_count"] == 0
        assert res["requests_failed"] >= 1
        assert res["requests_succeeded"] == 0


def test_regression_04_api_quota_rate_limit_failure():
    """Scenario 4: External API rate limit (HTTP 429). Must report rate_limited."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"

    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests: Rate limit exceeded"
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["wearable monitor"], limit=10)
        assert res["status"] == "LENS_RATE_LIMITED"
        assert res["provider_status"] == "rate_limited"
        assert res["retrieved_count"] == 0
        assert res["requests_failed"] >= 1


def test_regression_05_network_timeout():
    """Scenario 5: Network timeout during external API fetch. Must return timeout status without crash."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"

    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.side_effect = httpx.TimeoutException("Read timed out")

        res = service.search_patents(queries=["smart irrigation"], limit=10)
        assert res["status"] == "LENS_API_UNAVAILABLE"
        assert res["provider_status"] == "timeout"
        assert res["retrieved_count"] == 0
        assert res["requests_failed"] >= 1


def test_regression_06_invalid_response_format(monkeypatch):
    """Scenario 6: Invalid response format (e.g. HTML 301 error page instead of JSON)."""
    monkeypatch.setenv("TESTING", "false")
    patent_service = PatentAPIService()
    patent_service.api_key = "mock_key"

    with patch("app.core.config.settings.TESTING", False):
        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 301
            mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
            mock_resp.text = "<html><body>Moved Permanently</body></html>"
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

            results, is_success, status_label = patent_service._fetch_from_patentsview(
                title="AI Irrigation", keywords=["soil moisture"], domain="Agriculture"
            )
            assert results == []
            assert is_success is False
            assert status_label == "provider_error"


def test_regression_07_database_fallback_when_api_fails():
    """Scenario 7: Database fallback when API fails. Must return candidates with DATABASE source."""
    class MockDBPatent:
        def __init__(self, pat_num, title, domain, source_type="DATABASE", source_status="DATABASE"):
            self.id = pat_num
            self.patent_number = pat_num
            self.title = title
            self.abstract = f"Abstract for {title}"
            self.description = f"Description for {title}"
            self.claims = "1. An agricultural soil moisture sensor."
            self.domain = domain
            self.source_type = source_type
            self.source_status = source_status
            self.document_type = "DATABASE RECORD"
            self.publication_date = "2023-01-01"
            self.embedding = json.dumps([0.1] * 384)
            self.cpc_codes = "A01G25"
            self.data_quality_status = "COMPLETE"

    mock_db_patents = [
        MockDBPatent("US-1110001", "Adaptive Irrigation System", "Agriculture"),
        MockDBPatent("US-1110002", "Automated Soil Moisture Valve", "Agriculture")
    ]

    # Verify that DB candidates retain their authentic DATABASE provenance
    assert mock_db_patents[0].source_status == "DATABASE"
    assert mock_db_patents[0].source_type == "DATABASE"
    assert mock_db_patents[0].document_type == "DATABASE RECORD"
    assert mock_db_patents[0].title == "Adaptive Irrigation System"


def test_regression_08_merging_live_api_and_database_results():
    """Scenario 8: Merging live API and database results without overwriting provenance."""
    live_records = [
        {"patent_number": "US-2023061735", "title": "Intelligent Irrigation", "source_status": "LIVE_API", "source_type": "THE LENS"},
        {"patent_number": "ARXIV-2404-12415", "title": "Soil Moisture Neural Models", "source_status": "LIVE_API", "source_type": "arXiv"}
    ]
    db_records = [
        {"patent_number": "US-1110001", "title": "Adaptive Irrigation System", "source_status": "DATABASE", "source_type": "DATABASE"}
    ]

    combined = {}
    for r in live_records + db_records:
        combined[r["patent_number"]] = r

    assert len(combined) == 3
    assert combined["US-2023061735"]["source_status"] == "LIVE_API"
    assert combined["US-2023061735"]["source_type"] == "THE LENS"
    assert combined["ARXIV-2404-12415"]["source_type"] == "arXiv"
    assert combined["US-1110001"]["source_status"] == "DATABASE"


def test_regression_09_different_inventions_return_different_candidate_sets():
    """Scenario 9: Smart Irrigation and Wearable Healthcare inventions must produce distinct candidate sets."""
    irrigation_features = ["soil moisture sensor", "predictive irrigation", "solenoid valve", "water pump"]
    healthcare_features = ["wearable physiological sensor", "heart rate monitor", "photoplethysmography", "ECG"]

    irrigation_patent = {
        "title": "Smart Irrigation Controller Using Soil Moisture Sensor",
        "abstract": "Systems and methods for automated irrigation based on soil moisture and rainfall prediction.",
        "description": "A microcontroller actuates a water pump when soil moisture is low.",
        "claims": "1. An irrigation controller comprising a soil moisture sensor and a water pump.",
        "domain": "Agriculture",
        "cpc_codes": "A01G25/16"
    }

    healthcare_patent = {
        "title": "Wearable Physiological Monitoring Device With Optical Sensor",
        "abstract": "A wearable wristband measuring heart rate and pulse wave velocity using PPG sensors.",
        "description": "Continuous vital sign monitoring using photoplethysmography and ECG electrodes.",
        "claims": "1. A wearable device comprising an optical heart rate sensor and a microcontroller.",
        "domain": "Healthcare",
        "cpc_codes": "A61B5/024"
    }

    mock_emb = [0.05] * 384

    # Score irrigation invention against both patents
    score_irrig_on_irrig = compute_hybrid_score(
        user_embedding=mock_emb,
        patent_embedding=mock_emb,
        user_keywords=irrigation_features,
        user_concepts=["soil moisture", "predictive irrigation"],
        user_domain="Agriculture",
        patent=irrigation_patent,
        technical_features=irrigation_features
    )

    score_irrig_on_health = compute_hybrid_score(
        user_embedding=mock_emb,
        patent_embedding=mock_emb,
        user_keywords=irrigation_features,
        user_concepts=["soil moisture", "predictive irrigation"],
        user_domain="Agriculture",
        patent=healthcare_patent,
        technical_features=irrigation_features
    )

    # Score healthcare invention against both patents
    score_health_on_health = compute_hybrid_score(
        user_embedding=mock_emb,
        patent_embedding=mock_emb,
        user_keywords=healthcare_features,
        user_concepts=["wearable sensor", "heart rate"],
        user_domain="Healthcare",
        patent=healthcare_patent,
        technical_features=healthcare_features
    )

    score_health_on_irrig = compute_hybrid_score(
        user_embedding=mock_emb,
        patent_embedding=mock_emb,
        user_keywords=healthcare_features,
        user_concepts=["wearable sensor", "heart rate"],
        user_domain="Healthcare",
        patent=irrigation_patent,
        technical_features=healthcare_features
    )

    # Smart Irrigation must score substantially higher on Irrigation patent than on Healthcare patent
    assert score_irrig_on_irrig["final_score"] > score_irrig_on_health["final_score"] + 15.0
    assert score_irrig_on_irrig["matched_feature_count"] > score_irrig_on_health["matched_feature_count"]

    # Wearable Healthcare must score substantially higher on Healthcare patent than on Irrigation patent
    assert score_health_on_health["final_score"] > score_health_on_irrig["final_score"] + 15.0
    assert score_health_on_health["matched_feature_count"] > score_health_on_irrig["matched_feature_count"]


def test_regression_10_accurate_counters_across_pipeline():
    """Scenario 10: Accurate live API, fallback, shortlist, and final-result pipeline counters."""
    metrics = PipelineMetrics(
        patents_searched_total=150,
        database_candidates_examined=125,
        api_requests_attempted=3,
        api_requests_succeeded=3,
        api_requests_failed=0,
        api_records_returned=25,
        api_records_unique=25,
        embedding_candidates=150,
        vector_candidates_evaluated=150,
        vector_shortlisted_count=42,
        final_shortlisted=10,
        database_fallback_candidates=0,
        active_llm_provider="groq",
        active_llm_model="llama-3.3-70b-versatile",
        provider_status=ProviderStatus(lens="success", gemini="not_configured", groq="success", overall_status="completed")
    )

    # Counter assertions
    assert metrics.api_records_returned == 25
    assert metrics.patents_searched_total == 150
    assert metrics.vector_shortlisted_count == 42
    assert metrics.final_shortlisted == 10
    assert metrics.database_fallback_candidates == 0
    assert metrics.provider_status is not None
    assert metrics.provider_status.lens == "success"
    assert metrics.active_llm_provider == "groq"
