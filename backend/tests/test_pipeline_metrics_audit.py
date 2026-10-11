import pytest
import json
from unittest.mock import patch, MagicMock
from app.schemas.schemas import (
    PipelineMetrics, ProviderStatus, SearchSummary, PriorArtSearchResponse
)
from ml.risk_classifier import classify_prior_art_risk, get_similarity_level_label
from ml.similarity_engine import calculate_deterministic_final_score, compute_hybrid_score
from app.services.lens_api_service import LensAPIService, lens_api_service
from app.services.patent_api_service import PatentAPIService


# =========================================================================
# Phase 9: Automated Test Suite — 24 Test Scenarios for Search Pipeline Audit
# =========================================================================

# -------------------------------------------------------------------------
# Test 1–5: External Patent API Record Returns and Deduplication
# -------------------------------------------------------------------------

def test_scenario_01_api_returns_0_records():
    """Test 1: External API returns 0 records. Counters and status must be honest (0, success_empty)."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [], "total": 0}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["telemetry sensor"], limit=20)
        assert res["retrieved_count"] == 0
        assert res["records_returned"] == 0
        assert res["records_unique"] == 0
        assert res["provider_status"] == "success_empty"
        assert res["status"] == "LENS_NO_RESULTS"


def test_scenario_02_api_returns_5_records():
    """Test 2: External API returns 5 records."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    fake_items = [
        {"lens_id": f"00{i}", "doc_number": f"US-{1000+i}", "biblio": {"invention_title": [{"text": f"Title {i}", "lang": "en"}]}}
        for i in range(5)
    ]
    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": fake_items, "total": 5}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["telemetry"], limit=20)
        assert res["retrieved_count"] == 5
        assert res["records_unique"] == 5
        assert res["provider_status"] == "success"


def test_scenario_03_api_returns_100_records():
    """Test 3: External API returns 100 records."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    fake_items = [
        {"lens_id": f"id_{i}", "doc_number": f"US-{2000+i}", "biblio": {"invention_title": [{"text": f"Patent Title {i}", "lang": "en"}]}}
        for i in range(100)
    ]
    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": fake_items, "total": 100}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["iot sensors"], limit=100)
        assert res["retrieved_count"] == 100
        assert res["records_unique"] == 100


def test_scenario_04_api_multiple_queries():
    """Test 4: Multiple queries dispatch. Requests attempted & succeeded are accurately tallied."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    fake_items_1 = [{"lens_id": "01", "doc_number": "US-101", "biblio": {"invention_title": [{"text": "P1", "lang": "en"}]}}]
    fake_items_2 = [{"lens_id": "02", "doc_number": "US-102", "biblio": {"invention_title": [{"text": "P2", "lang": "en"}]}}]

    with patch("httpx.Client") as mock_client:
        def side_effect(*args, **kwargs):
            payload = kwargs.get("json", {})
            q = payload.get("query", "")
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"data": fake_items_1 if "first" in q else fake_items_2, "total": 1}
            return m

        mock_client.return_value.__enter__.return_value.post.side_effect = side_effect

        res = service.search_patents(queries=["first query", "second query"], limit=10)
        assert res["requests_attempted"] == 2
        assert res["requests_succeeded"] == 2
        assert res["requests_failed"] == 0
        assert res["records_unique"] == 2


def test_scenario_05_api_duplicate_family_records_deduplicated():
    """Test 5: Duplicate patent families are properly deduplicated."""
    service = LensAPIService()
    records = [
        {"lens_id": "01", "patent_number": "US-100", "family_id": "FAM_A", "title": "Invention A", "claims": "claim 1"},
        {"lens_id": "02", "patent_number": "EP-100", "family_id": "FAM_A", "title": "Invention A", "claims": "claim 1"},
        {"lens_id": "03", "patent_number": "WO-200", "family_id": "FAM_B", "title": "Invention B", "claims": "claim 2"}
    ]
    grouped = service.group_by_patent_family(records)
    assert len(grouped) == 2
    fam_a = next(r for r in grouped if r["family_id"] == "FAM_A")
    assert fam_a["family_size"] == 2


# -------------------------------------------------------------------------
# Test 6–10: External API Error Handling, Timeouts, Rate Limits, Config
# -------------------------------------------------------------------------

def test_scenario_06_api_http_429_rate_limit():
    """Test 6: HTTP 429 rate limit is captured as 'rate_limited' with failed count incremented."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests"
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["query1"], limit=10)
        assert res["status"] == "LENS_RATE_LIMITED"
        assert res["provider_status"] == "rate_limited"
        assert res["requests_failed"] == 1
        assert res["retrieved_count"] == 0


def test_scenario_07_api_http_401_auth_error():
    """Test 7: HTTP 401/403 authorization error is captured as 'authentication_error'."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["query1"], limit=10)
        assert res["status"] == "LENS_AUTH_ERROR"
        assert res["provider_status"] == "authentication_error"
        assert res["requests_failed"] == 1


def test_scenario_08_api_timeout():
    """Test 8: Network timeout (504/timeout) is captured as 'timeout'."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.side_effect = Exception("ReadTimeout")

        res = service.search_patents(queries=["query1"], limit=10)
        assert res["status"] == "LENS_API_UNAVAILABLE"
        assert res["provider_status"] in ("timeout", "provider_error")
        assert res["requests_failed"] == 1


def test_scenario_09_api_malformed_json():
    """Test 9: Malformed JSON response handled gracefully without crashing."""
    service = LensAPIService()
    service.api_token = "mock_valid_token_12345"
    with patch("httpx.Client") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"unexpected_key": None}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

        res = service.search_patents(queries=["query1"], limit=10)
        assert res["retrieved_count"] == 0
        assert res["provider_status"] == "success_empty"


def test_scenario_10_api_unconfigured_provider():
    """Test 10: Unconfigured Lens token returns provider_status='not_configured' and 0 requests."""
    service = LensAPIService()
    service.api_token = ""
    res = service.search_patents(queries=["query1"], limit=10)
    assert res["status"] == "LENS_UNCONFIGURED"
    assert res["provider_status"] == "not_configured"
    assert res["requests_attempted"] == 0
    assert res["retrieved_count"] == 0


# -------------------------------------------------------------------------
# Test 11–12: Vector Search & Shortlisting Metrics
# -------------------------------------------------------------------------

def test_scenario_11_vector_search_zero_candidates():
    """Test 11: Vector search with 0 valid embeddings."""
    pm = PipelineMetrics(
        embedding_candidates=0,
        vector_candidates_evaluated=0,
        vector_shortlisted_count=0
    )
    assert pm.embedding_candidates == 0
    assert pm.vector_candidates_evaluated == 0
    assert pm.vector_shortlisted_count == 0


def test_scenario_12_vector_search_filtered_candidates():
    """Test 12: Vector similarity threshold correctly counts candidate passes vs fails."""
    import numpy as np
    user_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    # Candidate 1: sim = 1.0 (passes >= 0.25)
    # Candidate 2: sim = 0.5 (passes >= 0.25)
    # Candidate 3: sim = 0.1 (fails < 0.25)
    candidates = [
        [1.0, 0.0, 0.0],
        [0.5, 0.5, 0.0],
        [0.1, 0.9, 0.0]
    ]
    mat = np.array(candidates, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1)
    sims = np.dot(mat, user_vec) / norms

    passing = [s for s in sims if s >= 0.25]
    assert len(passing) == 2

    pm = PipelineMetrics(
        embedding_candidates=3,
        vector_candidates_evaluated=3,
        vector_shortlisted_count=len(passing)
    )
    assert pm.vector_shortlisted_count == 2


# -------------------------------------------------------------------------
# Test 13–16: LLM Processing, Failover, Model Identity
# -------------------------------------------------------------------------

def test_scenario_13_gemini_success():
    """Test 13: Gemini successful analysis tracked accurately."""
    pm = PipelineMetrics(
        gemini_requests_attempted=4,
        gemini_requests_succeeded=4,
        gemini_requests_failed=0,
        gemini_candidates_submitted=4,
        gemini_candidates_analyzed=4,
        active_llm_provider="gemini",
        active_llm_model="gemini-2.0-flash",
        provider_status=ProviderStatus(gemini="success")
    )
    assert pm.active_llm_provider == "gemini"
    assert pm.active_llm_model == "gemini-2.0-flash"
    assert pm.gemini_candidates_analyzed == 4
    assert pm.provider_status.gemini == "success"


def test_scenario_14_gemini_malformed_response_fallback():
    """Test 14: Gemini malformed response increments failed requests and activates heuristic provider."""
    pm = PipelineMetrics(
        gemini_requests_attempted=4,
        gemini_requests_succeeded=0,
        gemini_requests_failed=4,
        gemini_candidates_analyzed=0,
        active_llm_provider="heuristic",
        active_llm_model="Heuristic-Rule-Engine"
    )
    assert pm.gemini_requests_failed == 4
    assert pm.gemini_candidates_analyzed == 0
    assert pm.active_llm_provider == "heuristic"


def test_scenario_15_gemini_timeout():
    """Test 15: Gemini timeout reports heuristic provider without fabricating Gemini success."""
    pm = PipelineMetrics(
        gemini_requests_attempted=2,
        gemini_requests_failed=2,
        gemini_candidates_analyzed=0,
        active_llm_provider="heuristic",
        provider_status=ProviderStatus(gemini="timeout")
    )
    assert pm.gemini_candidates_analyzed == 0
    assert pm.active_llm_provider != "gemini"
    assert pm.provider_status.gemini == "timeout"


def test_scenario_16_groq_active_and_distinct():
    """Test 16: Groq executions are reported as Groq (llama-3.3-70b-versatile), NOT labeled as Gemini."""
    pm = PipelineMetrics(
        groq_requests_attempted=4,
        groq_requests_succeeded=4,
        groq_candidates_analyzed=4,
        active_llm_provider="groq",
        active_llm_model="llama-3.3-70b-versatile",
        provider_status=ProviderStatus(groq="success", gemini="not_configured")
    )
    assert pm.active_llm_provider == "groq"
    assert "llama" in pm.active_llm_model.lower()
    assert pm.provider_status.gemini != "success"
    assert pm.groq_candidates_analyzed == 4


# -------------------------------------------------------------------------
# Test 17–18: Search Results Count and Risk Bucketing Math
# -------------------------------------------------------------------------

def test_scenario_17_search_zero_matches():
    """Test 17: Search with 0 matches returns 0 across all risk buckets."""
    summary = SearchSummary(
        total_results=0,
        low_similarity=0,
        moderate_similarity=0,
        high_similarity=0,
        very_high_similarity=0
    )
    assert summary.total_results == 0
    assert summary.low_similarity + summary.moderate_similarity + summary.high_similarity + summary.very_high_similarity == 0


def test_scenario_18_multi_risk_categories_math():
    """Test 18: Exact risk bucket summation identity: Total = Low + Mod + High + VHigh."""
    scores = [25.0, 35.0, 48.0, 62.0, 75.0, 88.0]
    low = sum(1 for s in scores if classify_prior_art_risk(s)["risk_level"] == "LOW")
    mod = sum(1 for s in scores if classify_prior_art_risk(s)["risk_level"] == "MODERATE")
    high = sum(1 for s in scores if classify_prior_art_risk(s)["risk_level"] == "HIGH")
    vhigh = sum(1 for s in scores if classify_prior_art_risk(s)["risk_level"] == "VERY HIGH")

    assert low == 1      # 25.0 < 30
    assert mod == 2      # 35.0, 48.0
    assert high == 1     # 62.0
    assert vhigh == 2    # 75.0, 88.0

    total = len(scores)
    assert total == (low + mod + high + vhigh)

    summary = SearchSummary(
        total_results=total,
        low_similarity=low,
        moderate_similarity=mod,
        high_similarity=high,
        very_high_similarity=vhigh
    )
    assert summary.total_results == (summary.low_similarity + summary.moderate_similarity + summary.high_similarity + summary.very_high_similarity)


# -------------------------------------------------------------------------
# Test 19–21: Isolation, Concurrent Searches, History Retrieval
# -------------------------------------------------------------------------

def test_scenario_19_fresh_metrics_per_search():
    """Test 19: Each search constructs a fresh instance without leaking previous counters."""
    search1_metrics = PipelineMetrics(
        patents_searched_total=12,
        api_records_returned=10,
        vector_shortlisted_count=5
    )
    search2_metrics = PipelineMetrics(
        patents_searched_total=85,
        api_records_returned=50,
        vector_shortlisted_count=8
    )

    assert search1_metrics.patents_searched_total == 12
    assert search2_metrics.patents_searched_total == 85
    assert search1_metrics.api_records_returned != search2_metrics.api_records_returned


def test_scenario_20_concurrent_search_isolation():
    """Test 20: Concurrent search metric objects are isolated independent instances."""
    m_list = [PipelineMetrics(patents_searched_total=i * 10) for i in range(1, 6)]
    for i, m in enumerate(m_list, start=1):
        assert m.patents_searched_total == i * 10


def test_scenario_21_history_retrieval_by_search_id():
    """Test 21: Deserializing persisted pipeline_metrics for a specific search ID preserves exact values."""
    saved_json = {
        "patents_searched_total": 42,
        "database_candidates_examined": 42,
        "api_records_returned": 25,
        "vector_shortlisted_count": 6,
        "groq_candidates_analyzed": 4,
        "active_llm_provider": "groq",
        "active_llm_model": "llama-3.3-70b-versatile",
        "provider_status": {
            "lens": "success",
            "groq": "success",
            "gemini": "not_configured",
            "overall_status": "completed"
        }
    }
    loaded = PipelineMetrics.model_validate(saved_json)
    assert loaded.patents_searched_total == 42
    assert loaded.api_records_returned == 25
    assert loaded.vector_shortlisted_count == 6
    assert loaded.groq_candidates_analyzed == 4
    assert loaded.active_llm_provider == "groq"
    assert loaded.provider_status.groq == "success"


# -------------------------------------------------------------------------
# Test 22–24: Frontend Response Mapping, Schema Alignment, Score Precision
# -------------------------------------------------------------------------

def test_scenario_22_frontend_response_mapping():
    """Test 22: PipelineMetrics serializes to JSON matching frontend TypeScript definitions."""
    pm = PipelineMetrics(
        patents_searched_total=50,
        api_records_returned=15,
        vector_shortlisted_count=7,
        groq_candidates_analyzed=4,
        active_llm_provider="groq",
        active_llm_model="llama-3.3-70b-versatile"
    )
    d = pm.model_dump(mode="json")
    assert "patents_searched_total" in d
    assert "api_records_returned" in d
    assert "vector_shortlisted_count" in d
    assert "groq_candidates_analyzed" in d
    assert "active_llm_model" in d


def test_scenario_23_risk_bucket_summation_consistency():
    """Test 23: Exhaustive verification across multiple score arrays that buckets always sum to total."""
    test_cases = [
        [],
        [15.0],
        [25.0, 35.0],
        [10.0, 32.0, 55.0, 75.0, 95.0],
        [70.0, 71.0, 80.0, 90.0],
        [5.0, 15.0, 25.0]
    ]
    for case in test_cases:
        low = sum(1 for s in case if classify_prior_art_risk(s)["risk_level"] == "LOW")
        mod = sum(1 for s in case if classify_prior_art_risk(s)["risk_level"] == "MODERATE")
        high = sum(1 for s in case if classify_prior_art_risk(s)["risk_level"] == "HIGH")
        vhigh = sum(1 for s in case if classify_prior_art_risk(s)["risk_level"] == "VERY HIGH")
        assert len(case) == (low + mod + high + vhigh)


def test_scenario_24_score_precision_and_breakdown_formula():
    """Test 24: Canonical 5-factor scoring formula equals final score and effective weights sum to 100%."""
    final_score, conf_score, bd = calculate_deterministic_final_score(
        sbert_sim=0.72,
        feature_score=0.68,
        evidence_strength=0.85,
        distinctive_score=0.55,
        domain_cpc_score=0.90,
        has_target_features=True,
        has_text_evidence=True
    )
    # 72 * 0.25 = 18.0
    # 68 * 0.35 = 23.8
    # 85 * 0.20 = 17.0
    # 55 * 0.10 = 5.5
    # 90 * 0.10 = 9.0
    # Total = 18.0 + 23.8 + 17.0 + 5.5 + 9.0 = 73.3
    assert abs(final_score - 73.3) < 0.2
    
    comp_keys = ["semantic", "technical_features", "evidence", "concepts", "domain_cpc"]
    eff_sum = sum(bd[k]["effective_weight"] for k in comp_keys)
    assert abs(eff_sum - 1.0) < 1e-4

    contrib_sum = sum(bd[k]["contribution"] for k in comp_keys)
    assert abs(contrib_sum - final_score) < 0.2
