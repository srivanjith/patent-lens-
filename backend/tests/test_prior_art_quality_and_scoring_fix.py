import os
import pytest
from typing import Dict, Any

os.environ["TESTING"] = "true"

from ml.keyword_extractor import (
    extract_atomic_technical_features,
    clean_technical_feature_phrase,
    extract_technical_concepts
)
from ml.similarity_engine import (
    compute_hybrid_score,
    calculate_deterministic_final_score,
    calculate_cosine_similarity
)
from ml.embedding_service import embedding_service


# Setup test embeddings
@pytest.fixture(scope="module")
def sbert_service():
    if not embedding_service.is_loaded:
        embedding_service.load_model()
    return embedding_service


def test_clean_technical_feature_phrase_no_broken_ngrams():
    """Verify that broken fragments with trailing/leading stopwords are cleaned properly."""
    assert clean_technical_feature_phrase("Sensor Readings With") == "Sensor Readings"
    assert clean_technical_feature_phrase("Valve When The") == "Valve"
    assert clean_technical_feature_phrase("Water Delivery Technical") == "Water Delivery"
    assert clean_technical_feature_phrase("  soil moisture sensor. ") == "Soil Moisture Sensor"
    assert not clean_technical_feature_phrase("A System For")


def test_smart_irrigation_feature_extraction():
    """Verify that atomic technical feature extraction produces distinctive, clean terms for Smart Irrigation."""
    title = "AI-Based Smart Irrigation System Using Soil Moisture and Weather Prediction"
    description = (
        "The system uses soil-moisture sensors, temperature and humidity sensors, and weather forecast data "
        "to estimate crop water requirements. A machine-learning model combines current sensor readings with "
        "historical irrigation and weather data to predict soil-moisture levels over the next several hours. "
        "A microcontroller activates a water pump or solenoid valve when the predicted moisture level falls below "
        "a crop-specific threshold. The controller delays irrigation when rainfall is forecast, records water consumption, "
        "and sends alerts to a farmer through a mobile application. The system supports adjustable thresholds for different crops "
        "and low-cost hardware for small farms."
    )
    keywords = [
        "soil moisture sensor", "predictive irrigation", "machine learning",
        "weather forecasting", "rainfall prediction", "automated water pump",
        "solenoid valve", "microcontroller", "crop-specific threshold", "water conservation"
    ]
    target_text = f"{title} {description}"
    features = extract_atomic_technical_features(target_text, top_n=9, user_keywords=keywords)
    
    assert len(features) >= 5
    # Distinctive irrigation features must be present
    features_lower = [f.lower() for f in features]
    assert any("soil moisture" in f for f in features_lower)
    assert any("solenoid valve" in f or "water pump" in f for f in features_lower)
    assert any("weather" in f or "rainfall" in f or "predictive irrigation" in f for f in features_lower)
    
    # Broken n-grams must NOT be present
    assert not any(f.endswith("with") or f.endswith("the") or f.endswith("when") for f in features_lower)


def test_exact_smart_irrigation_scoring_against_irrigation_patent(sbert_service):
    """
    Test exact failing Smart Irrigation input scored against actual prior-art irrigation patent.
    Verifies:
      - Numerator and Denominator consistency (> 0, non-zero denominator)
      - Technical similarity is relevant (not 0/0)
      - Verbatim evidence verification (quotes exist in patent text)
      - 5-component formula consistency
    """
    irrigation_patent = {
        "title": "AI-Driven Precision Soil Moisture Analysis and Variable-Rate Automated Irrigation System",
        "abstract": "An automated agricultural irrigation network incorporating subterranean soil moisture sensors, weather API forecasts, and machine learning models for optimized crop watering schedules.",
        "description": "The system utilizes distributed moisture and NPK sensor arrays transmitting soil telemetry via LoRaWAN to a central edge controller. A predictive machine learning model computes daily evapotranspiration rates and controls variable-rate solenoid valves to minimize water wastage while preserving crop yield.",
        "claims": "1. An automated irrigation system comprising a plurality of subterranean soil moisture sensors, a microcontroller receiving weather forecast data, and at least one solenoid valve operated to deliver water when predicted soil moisture falls below a threshold.",
        "cpc_codes": "A01G 25/16, G05B 13/02",
        "domain": "Agriculture"
    }

    user_text = (
        "AI-Based Smart Irrigation System Using Soil Moisture and Weather Prediction. "
        "The system uses soil-moisture sensors, temperature and humidity sensors, and weather forecast data to estimate crop water requirements. "
        "A microcontroller activates a water pump or solenoid valve when the predicted moisture level falls below a crop-specific threshold."
    )
    user_emb = sbert_service.generate_embedding(user_text)
    patent_text = f"{irrigation_patent['title']} {irrigation_patent['abstract']} {irrigation_patent['description']}"
    patent_emb = sbert_service.generate_embedding(patent_text)

    keywords = ["soil moisture sensor", "predictive irrigation", "solenoid valve", "weather forecasting", "microcontroller"]
    features = extract_atomic_technical_features(user_text, top_n=6, user_keywords=keywords)

    score_res = compute_hybrid_score(
        user_embedding=user_emb,
        patent_embedding=patent_emb,
        user_keywords=keywords,
        user_concepts=keywords[:3],
        user_domain="Artificial Intelligence",
        patent=irrigation_patent,
        target_text_for_concepts=user_text,
        technical_features=features
    )

    # 1. Denominator and Numerator Checks
    num = score_res["matched_feature_count"]
    den = score_res["total_feature_count"]
    assert den >= 5
    assert num >= 2, f"Expected at least 2 matching features for irrigation patent, got {num}"
    assert num == len(score_res["strong_matches"]) + len(score_res["partial_matches"])
    assert den == len(score_res["strong_matches"]) + len(score_res["partial_matches"]) + len(score_res["missing_features"])

    # 2. Technical Score consistency
    expected_feat_score = round(((len(score_res["strong_matches"]) * 1.0 + len(score_res["partial_matches"]) * 0.5) / den) * 100.0, 1)
    assert abs(score_res["keyword_score"] - expected_feat_score) < 0.1

    # 3. Evidence Verification Checks
    verified_items = [item for item in score_res["evidence_items"] if item["verified"]]
    assert len(verified_items) >= 1, "At least one verified evidence item must be found in patent text"
    for item in verified_items:
        quote = item["evidence"]
        assert quote != "", "Verified item must have non-empty quote"
        # Quote must be verbatim substring in substantive patent text
        full_spec = f"{irrigation_patent['claims']} {irrigation_patent['abstract']} {irrigation_patent['description']}".lower()
        assert quote.lower() in full_spec, f"Quote '{quote}' was not found in patent text"

    # 4. Score Breakdown checks
    bd = score_res["score_breakdown"]
    tf_comp = bd["technical_features"]
    assert tf_comp["status"] == "AVAILABLE"
    assert tf_comp["value"] == score_res["keyword_score"]
    assert tf_comp["weight"] == 0.35


def test_validation_case_1_unrelated_invention_yields_zero_match_and_low_risk(sbert_service):
    """
    Validation Case 1: Totally unrelated invention (cryptographic blockchain consensus)
    evaluated against irrigation patent -> 0 technical match, LOW TECHNICAL SIMILARITY, NO-RISK/LOW-RISK.
    """
    irrigation_patent = {
        "title": "Variable-Rate Automated Irrigation System",
        "abstract": "Automated agricultural irrigation network using soil moisture sensors and solenoid valves.",
        "description": "NPK sensor arrays and moisture telemetry regulate irrigation pump cycles.",
        "claims": "1. A subterranean soil moisture sensor coupled to a water pipe valve.",
        "domain": "Agriculture"
    }

    crypto_text = "Zero-Knowledge Rollup Proof Verification for Decentralized Blockchain Smart Contract State Transitions"
    crypto_emb = sbert_service.generate_embedding(crypto_text)
    pat_emb = sbert_service.generate_embedding(irrigation_patent["abstract"])

    crypto_features = ["zero-knowledge proof", "blockchain state transition", "smart contract execution", "elliptic curve cryptography"]

    score_res = compute_hybrid_score(
        user_embedding=crypto_emb,
        patent_embedding=pat_emb,
        user_keywords=crypto_features,
        user_concepts=crypto_features[:2],
        user_domain="Cybersecurity & Software",
        patent=irrigation_patent,
        target_text_for_concepts=crypto_text,
        technical_features=crypto_features
    )

    assert score_res["matched_feature_count"] == 0
    assert len(score_res["strong_matches"]) == 0
    assert len(score_res["partial_matches"]) == 0
    assert score_res["keyword_score"] == 0.0
    # Must NOT have 74% or high score
    assert score_res["final_score"] < 40.0
    bd = score_res["score_breakdown"]
    assert bd["technical_features"]["value"] == 0.0


def test_validation_case_2_missing_specification_text_caps_confidence(sbert_service):
    """
    Validation Case 2: Patent with missing claims and description (empty text)
    -> evidence status UNAVAILABLE, confidence score clamped <= 25%.
    """
    empty_patent = {
        "title": "Brief Abstract Only Record",
        "abstract": "A short summary without detailed claims or specification.",
        "description": "",
        "claims": "",
        "domain": "Artificial Intelligence"
    }

    user_text = "Microcontroller based threshold irrigation control"
    user_emb = sbert_service.generate_embedding(user_text)
    pat_emb = sbert_service.generate_embedding(empty_patent["abstract"])

    features = ["microcontroller", "threshold irrigation", "moisture measurement"]

    score_res = compute_hybrid_score(
        user_embedding=user_emb,
        patent_embedding=pat_emb,
        user_keywords=features,
        user_concepts=features,
        user_domain="Artificial Intelligence",
        patent=empty_patent,
        target_text_for_concepts=user_text,
        technical_features=features
    )

    assert score_res["claims_status"] == "NOT_AVAILABLE"
    assert score_res["full_text_status"] == "NOT_AVAILABLE"
    # Confidence score MUST be clamped <= 25.0%
    assert score_res["confidence_score"] <= 25.0
    bd = score_res["score_breakdown"]
    assert bd["evidence"]["status"] == "UNAVAILABLE"
    assert bd["evidence"]["value"] is None


def test_validation_case_3_unverified_hallucinated_quote_rejected(sbert_service):
    """
    Validation Case 3: If an evidence quote is synthetic/hallucinated (not in patent text),
    it is marked UNVERIFIED and evidence strength is 0.0.
    """
    real_patent = {
        "title": "Subterranean Irrigation Valve Device",
        "abstract": "A water valve mechanism designed for buried agricultural pipelines.",
        "description": "Mechanical diaphragm valve responding to hydraulic line pressure.",
        "claims": "1. A hydraulic valve comprising a diaphragm and spring bias.",
        "domain": "Agriculture"
    }

    user_text = "Photonic quantum computing circuit using cryogenic microwave resonators"
    user_emb = sbert_service.generate_embedding(user_text)
    pat_emb = sbert_service.generate_embedding(real_patent["abstract"])

    # Target features that do not exist in patent
    features = ["cryogenic microwave resonator", "photonic quantum circuit"]

    score_res = compute_hybrid_score(
        user_embedding=user_emb,
        patent_embedding=pat_emb,
        user_keywords=features,
        user_concepts=features,
        user_domain="Quantum Computing",
        patent=real_patent,
        target_text_for_concepts=user_text,
        technical_features=features
    )

    # All items must be unverified
    for item in score_res["evidence_items"]:
        assert item["verified"] is False
        assert item["verification_status"] == "UNVERIFIED"
    assert score_res["evidence_score"] == 0.0
    assert score_res["confidence_score"] <= 25.0


def test_validation_case_4_multi_sensor_agricultural_patent(sbert_service):
    """
    Validation Case 4: Multi-sensor agricultural patent with moisture, LoRaWAN, and NPK
    evaluated against multi-sensor query -> realistic numerator/denominator, strong matches.
    """
    multi_sensor_patent = {
        "title": "LoRaWAN Distributed Multi-Sensor Soil Telemetry System",
        "abstract": "A multi-sensor agricultural network integrating soil moisture sensors and temperature sensors communicating via LoRaWAN.",
        "description": "Distributed field nodes measure volumetric water content and ambient temperature, relaying data to a central gateway.",
        "claims": "1. A system comprising multiple soil moisture sensors and a wireless LoRaWAN transceiver.",
        "domain": "Agriculture"
    }

    user_text = "Wireless soil moisture sensor network using temperature sensors and LoRaWAN"
    user_emb = sbert_service.generate_embedding(user_text)
    pat_emb = sbert_service.generate_embedding(multi_sensor_patent["abstract"])

    features = ["soil moisture sensor", "temperature sensor", "lorawan", "volumetric water content"]

    score_res = compute_hybrid_score(
        user_embedding=user_emb,
        patent_embedding=pat_emb,
        user_keywords=features,
        user_concepts=features[:2],
        user_domain="Agriculture",
        patent=multi_sensor_patent,
        target_text_for_concepts=user_text,
        technical_features=features
    )

    assert score_res["matched_feature_count"] >= 3
    assert score_res["total_feature_count"] == 4
    assert score_res["keyword_score"] >= 60.0
    assert len(score_res["strong_matches"]) >= 2
    assert score_res["matched_feature_count"] == len(score_res["strong_matches"]) + len(score_res["partial_matches"])


def test_validation_case_5_generic_ml_patent_separated_from_irrigation(sbert_service):
    """
    Validation Case 5: Generic ML patent (Convolutional Neural Network for Image Recognition)
    evaluated against Smart Irrigation invention -> Low technical match, domain penalty applied,
    distinctive concept penalty protects against false positive.
    """
    cv_patent = {
        "title": "Convolutional Neural Network for Image Recognition",
        "abstract": "A deep learning framework utilizing convolutional neural networks to classify digital images.",
        "description": "Multi-layer feature maps and pooling layers detect visual patterns in video frames.",
        "claims": "1. An image classification system comprising convolutional filters.",
        "domain": "Artificial Intelligence"
    }

    irrigation_text = (
        "AI-Based Smart Irrigation System Using Soil Moisture and Weather Prediction. "
        "A microcontroller activates a water pump or solenoid valve when predicted soil moisture falls below threshold."
    )
    irrigation_emb = sbert_service.generate_embedding(irrigation_text)
    cv_emb = sbert_service.generate_embedding(cv_patent["abstract"])

    irrigation_features = [
        "soil moisture sensor", "predictive irrigation", "solenoid valve", "water pump", "crop-specific threshold"
    ]
    distinctive_features = ["soil moisture sensor", "predictive irrigation", "solenoid valve"]

    score_res = compute_hybrid_score(
        user_embedding=irrigation_emb,
        patent_embedding=cv_emb,
        user_keywords=irrigation_features,
        user_concepts=irrigation_features[:3],
        user_domain="Agriculture",
        patent=cv_patent,
        target_text_for_concepts=irrigation_text,
        distinctive_features=distinctive_features,
        technical_features=irrigation_features
    )

    # Should have 0 technical matches to irrigation hardware
    assert score_res["matched_feature_count"] == 0
    assert score_res["keyword_score"] == 0.0
    # False positive protection must penalize semantic similarity
    assert score_res["distinctive_score"] == 0.0
    # Final score capped at low relevance
    assert score_res["final_score"] <= 40.0
    assert score_res["score_breakdown"]["is_gated"] is True
