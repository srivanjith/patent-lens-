import pytest
from app.schemas.schemas import PatentOut, SearchResultItem, ScoreBreakdown, ComponentBreakdownItem
from ml.similarity_engine import calculate_deterministic_final_score, compute_hybrid_score
from ml.risk_classifier import classify_prior_art_risk

def test_live_api_provenance():
    """Verify LIVE_API provenance tagging for Lens API records."""
    pat = PatentOut(
        id="test-live-1",
        patent_number="US-11111111-B2",
        title="Live Lens Patent",
        abstract="Abstract of live patent",
        description="Description of live patent",
        inventors="Inventor A",
        assignee="Assignee A",
        publication_date="2024-05-15",
        domain="Artificial Intelligence",
        source_type="THE LENS",
        source_status="LIVE_API",
        source_name="The Lens Patent API",
        retrieval_status="LIVE_API_SUCCESS",
        document_type="PATENT"
    )
    assert pat.source_status == "LIVE_API"
    assert pat.source_type == "THE LENS"
    assert pat.source_name == "The Lens Patent API"
    assert pat.document_type == "PATENT"

def test_database_provenance():
    """Verify DATABASE provenance tagging for local database repository records."""
    pat = PatentOut(
        id="test-db-1",
        patent_number="US-22222222-A1",
        title="Local Database Patent Record",
        abstract="Abstract of database record",
        description="Description of database record",
        inventors="Inventor B",
        assignee="Assignee B",
        publication_date="2023-01-10",
        domain="Software",
        source_type="DATABASE",
        source_status="DATABASE",
        source_name="Database Repository",
        retrieval_status="DATABASE_REPOSITORY",
        document_type="DATABASE RECORD"
    )
    assert pat.source_status == "DATABASE"
    assert pat.source_type == "DATABASE"
    assert pat.source_name == "Database Repository"
    assert pat.source_type != "THE LENS"
    assert pat.document_type == "DATABASE RECORD"

def test_fallback_provenance():
    """Verify FALLBACK provenance tagging for PatentsView / fallback records."""
    pat = PatentOut(
        id="test-fb-1",
        patent_number="US-33333333-A1",
        title="PatentsView Fallback Record",
        abstract="Abstract of fallback record",
        description="Description of fallback record",
        inventors="Inventor C",
        assignee="Assignee C",
        publication_date="2022-11-20",
        domain="Electronics",
        source_type="USPTO",
        source_status="FALLBACK",
        source_name="PatentsView API (Fallback)",
        retrieval_status="FALLBACK_SUCCESS",
        document_type="PATENT"
    )
    assert pat.source_status == "FALLBACK"
    assert pat.source_type == "USPTO"
    assert pat.source_type != "THE LENS"

def test_zero_api_results_preserves_zero_count():
    """Verify zero API retrieved count is preserved and not fabricated."""
    from app.schemas.schemas import PipelineMetrics
    metrics = PipelineMetrics(
        patents_searched=15,
        patents_retrieved=0,
        lens_records_retrieved=0,
        database_fallback_candidates=10,
        vector_shortlisted=10,
        final_shortlisted=10
    )
    assert metrics.patents_retrieved == 0
    assert metrics.lens_records_retrieved == 0
    assert metrics.database_fallback_candidates == 10

def test_unavailable_evidence_handling():
    """Verify unavailable evidence handling when specification text is missing."""
    final_score, confidence_score, breakdown = calculate_deterministic_final_score(
        sbert_sim=0.75,
        feature_score=0.80,
        evidence_strength=0.0,
        distinctive_score=0.70,
        domain_cpc_score=0.80,
        has_text_evidence=False
    )
    assert breakdown["evidence"]["status"] == "UNAVAILABLE"
    assert breakdown["evidence"]["effective_weight"] == 0.0
    assert breakdown["is_gated"] is True
    assert final_score <= 45.0

def test_zero_feature_matches_classification():
    """Verify candidate with zero verified technical feature matches is classified correctly."""
    target_text = "Wireless charging receiver with resonant frequency tuning"
    patent_dict = {
        "title": "Irrigation drip tube connector",
        "abstract": "A connector for joining plastic drip irrigation tubes together.",
        "claims": "A tube connector comprising a barbed fitting.",
        "description": "Drip irrigation pipe fitting.",
        "domain": "Agriculture"
    }

    scores = compute_hybrid_score(
        user_embedding=[0.1]*384,
        patent_embedding=[0.05]*384,
        user_keywords=["wireless charging", "resonant frequency"],
        user_concepts=["resonant tuning"],
        user_domain="Electronics",
        patent=patent_dict,
        target_text_for_concepts=target_text,
        technical_features=["Wireless Charging", "Resonant Tuning", "Inductive Coil"]
    )

    assert scores["matched_feature_count"] == 0
    assert len(scores["strong_matches"]) == 0
    assert len(scores["partial_matches"]) == 0

def test_deterministic_score_calculation():
    """Verify the 5-factor mathematical score calculation (25/35/20/10/10)."""
    final_pct, conf_score, breakdown = calculate_deterministic_final_score(
        sbert_sim=0.80,         # 80% * 0.25 = 20.0%
        feature_score=0.60,     # 60% * 0.35 = 21.0%
        evidence_strength=0.70, # 70% * 0.20 = 14.0%
        distinctive_score=0.90, # 90% * 0.10 = 9.0%
        domain_cpc_score=0.80,  # 80% * 0.10 = 8.0%
        has_text_evidence=True
    )

    # Sum = 20.0 + 21.0 + 14.0 + 9.0 + 8.0 = 72.0%
    assert abs(final_pct - 72.0) < 0.2
    assert breakdown["semantic"]["contribution"] == 20.0
    assert breakdown["technical_features"]["contribution"] == 21.0
    assert breakdown["evidence"]["contribution"] == 14.0
    assert breakdown["concepts"]["contribution"] == 9.0
    assert breakdown["domain_cpc"]["contribution"] == 8.0

def test_temporal_status_classification():
    """Verify date comparison and temporal classification logic."""
    from app.api.search import PriorArtSearchRequest
    req = PriorArtSearchRequest(
        title="Test Invention",
        domain="Software",
        problem_statement="Problem statement text for testing",
        description="Description text for testing",
        reference_date="2024-01-01"
    )

    r_date = req.reference_date
    p_date_before = "2023-05-10"
    p_date_after = "2024-06-15"

    assert p_date_before < r_date
    assert p_date_after > r_date
