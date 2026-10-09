from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict

# --- Auth Schemas ---

class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=100)
    confirm_password: str

    @field_validator("confirm_password")
    def passwords_match(cls, v, info):
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match.")
        return v


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = "Google User"


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)


class OTPResendRequest(BaseModel):
    email: EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    is_verified: bool = False
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    require_otp: bool = False
    otp_sent_to: Optional[str] = None
    demo_otp: Optional[str] = None
    user: Optional[UserOut] = None


class UserUpdateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6, max_length=100)


# --- Patent Schemas ---

class PatentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patent_number: str
    lens_id: Optional[str] = None
    title: str
    abstract: str
    description: str
    claims: Optional[str] = None
    inventors: str
    assignee: str
    publication_date: str
    priority_date: Optional[str] = None
    earliest_priority_date: Optional[str] = None
    filing_date: Optional[str] = None
    grant_date: Optional[str] = None
    domain: str
    source_url: Optional[str] = None
    source_type: Optional[str] = "DATABASE"
    source_status: Optional[str] = "DATABASE"
    source_name: Optional[str] = "Database Repository"
    retrieval_status: Optional[str] = "DATABASE_REPOSITORY"
    document_type: Optional[str] = "DATABASE RECORD"
    cpc_codes: Optional[str] = None
    ipc_codes: Optional[str] = None
    jurisdiction: Optional[str] = None
    has_abstract: bool = True
    has_claims: bool = False
    has_description: bool = False
    has_full_text: bool = False
    simple_family_id: Optional[str] = None
    simple_family_size: Optional[int] = 1
    extended_family_size: Optional[int] = 1
    citations_count: Optional[int] = 0
    cited_by_count: Optional[int] = 0
    data_quality_status: Optional[str] = "LIMITED"
    created_at: Optional[datetime] = None


class CreateCustomPatentRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    abstract: str = Field(..., min_length=10, max_length=2000)
    description: str = Field(..., min_length=20, max_length=10000)
    domain: str = Field(..., min_length=2, max_length=100)
    inventors: Optional[str] = "User Inventor"
    assignee: Optional[str] = "Independent Assignee"


# --- Prior-Art Search Schemas ---

class PriorArtSearchRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=300)
    domain: str = Field(..., min_length=2, max_length=100)
    problem_statement: str = Field(..., min_length=10, max_length=2000)
    description: str = Field(..., min_length=20, max_length=10000)
    keywords: List[str] = Field(default_factory=list, max_length=20)
    reference_date: Optional[str] = Field(default=None, description="Optional user-supplied invention/reference date (YYYY-MM-DD)")


class FeatureComparisonItem(BaseModel):
    target_feature: str
    prior_art_feature: str
    match_level: str  # STRONG_MATCH, PARTIAL_MATCH, WEAK_MATCH, NOT_FOUND, UNABLE_TO_VERIFY
    explanation: str
    evidence_quote: Optional[str] = None
    evidence_source: Optional[str] = None
    evidence_text_origin: Optional[str] = None
    verification_status: str = "UNVERIFIED"
    confidence: Optional[float] = None


class MatchedFeatureItem(BaseModel):
    feature: str
    match_level: str  # STRONG_MATCH, PARTIAL_MATCH, WEAK_MATCH, NOT_FOUND, UNABLE_TO_VERIFY
    evidence: str


class ClaimElementItem(BaseModel):
    limitation_number: int
    element_text: str
    status: str  # STRONG_MATCH, PARTIAL_MATCH, WEAK_MATCH, NOT_FOUND, UNABLE_TO_VERIFY
    evidence_quote: Optional[str] = None
    explanation: str


class ComponentBreakdownItem(BaseModel):
    value: Optional[float] = None
    weight: float
    effective_weight: float
    contribution: float
    status: str = "AVAILABLE"  # "AVAILABLE" or "UNAVAILABLE"


class ScoreBreakdown(BaseModel):
    semantic: ComponentBreakdownItem
    technical_features: ComponentBreakdownItem
    evidence: ComponentBreakdownItem
    concepts: ComponentBreakdownItem
    domain_cpc: ComponentBreakdownItem
    semantic_similarity: float = 0.0  # 25% weight
    technical_features_score: float = 0.0   # 35% weight
    evidence_strength: float = 0.0    # 20% weight
    distinctive_concepts: float = 0.0 # 10% weight
    domain_cpc_alignment: float = 0.0 # 10% weight
    technology_domain_score: Optional[float] = 0.0
    cpc_match_score: Optional[float] = 0.0
    final_score: float = 0.0
    confidence_score: float = 0.0
    calculation_method: str = "STANDARD_FULL_WEIGHTS"
    is_gated: bool = False
    score_cap: Optional[float] = None
    score_cap_reason: Optional[str] = None
    formula_explanation: str = "Final Score = (25% Semantic) + (35% Technical Features) + (20% Evidence) + (10% Distinctive Concepts) + (10% Domain/CPC)"


class PatentFamilyMember(BaseModel):
    patent_number: str
    jurisdiction: str = "US"
    kind: Optional[str] = "A1"
    title: str = ""
    publication_date: str = "2024-01-01"
    document_type: str = "PATENT"
    source_url: str = ""


class PipelineMetrics(BaseModel):
    patents_searched: int = 0
    patents_retrieved: int = 0
    lens_records_retrieved: int = 0
    database_fallback_candidates: int = 0
    final_shortlisted: int = 0
    total_candidates_evaluated: int = 0
    raw_candidates: int = 0
    candidates_with_family_ids: int = 0
    post_dedup_candidates: int = 0
    vector_shortlisted: int = 0
    unique_families: int = 0
    semantic_candidates: int = 0
    technical_candidates: int = 0
    patents_with_claims: int = 0
    patents_with_full_text: int = 0
    evidence_verified_matches: int = 0
    iterative_wave_retrieved: int = 0
    citation_expansions_found: int = 0
    lens_api_status: Optional[str] = "LENS_OK"



class EvidenceItem(BaseModel):
    feature: str
    status: str = "unverified"
    similarity: float = 0.0
    evidence: str = ""
    evidence_text: Optional[str] = ""
    evidence_quote: Optional[str] = None
    evidence_source: Optional[str] = "NOT_AVAILABLE"
    evidence_text_origin: Optional[str] = "NOT_AVAILABLE"
    source: str = "NOT_AVAILABLE"
    source_section: str = "NOT_AVAILABLE"
    match_status: str = "UNVERIFIED"
    verification_status: str = "UNVERIFIED"
    verified: bool = False


class SearchResultItem(BaseModel):
    patent: PatentOut
    semantic_score: float
    keyword_score: float
    domain_score: float
    final_score: float
    confidence_score: float = 0.0
    matched_concepts: List[str]
    rank: int
    semantic_similarity_label: Optional[str] = "Moderate"
    relevance_explanation: Optional[str] = None
    feature_comparison: List[FeatureComparisonItem] = Field(default_factory=list)
    patent_specific_insights: List[str] = Field(default_factory=list)
    technical_features: List[str] = Field(default_factory=list)
    essential_features: List[str] = Field(default_factory=list)
    optional_features: List[str] = Field(default_factory=list)
    structured_quadruplets: List[Dict[str, Any]] = Field(default_factory=list)
    distinctive_features: List[str] = Field(default_factory=list)
    matched_features: List[MatchedFeatureItem] = Field(default_factory=list)
    strong_matches: List[str] = Field(default_factory=list)
    partial_matches: List[str] = Field(default_factory=list)
    weak_matches: List[str] = Field(default_factory=list)
    missing_features: List[str] = Field(default_factory=list)
    unmatched_features: List[str] = Field(default_factory=list)
    unverifiable_features: List[str] = Field(default_factory=list)
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    evidence_status_label: str = "Limited evidence (0% verified)"
    overlap_summary: Optional[str] = None
    claim_elements: List[ClaimElementItem] = Field(default_factory=list)
    single_document_anticipation: Optional[str] = "NO"
    missing_elements: List[str] = Field(default_factory=list)
    technical_feature_coverage: Optional[float] = 0.0
    evidence_confidence: Optional[float] = 0.0
    overall_result: Optional[str] = "NON_ANTICIPATED"
    score_breakdown: Optional[ScoreBreakdown] = None
    family_members: List[PatentFamilyMember] = Field(default_factory=list)
    family_size: int = 1
    is_family_representative: bool = True
    family_id: Optional[str] = None
    temporal_status: str = "BEFORE_REFERENCE_DATE"
    result_status: Optional[str] = None
    relevance_level: Optional[str] = None
    evidence_status: Optional[str] = None
    evidence_availability_level: Optional[str] = "NOT_VERIFIABLE"
    source_status: Optional[str] = "DATABASE"
    source_name: Optional[str] = "Database Repository"
    retrieval_status: Optional[str] = "DATABASE_REPOSITORY"
    feature_match_status: Optional[str] = "NOT_VERIFIABLE"
    feature_match_source: Optional[str] = "ABSTRACT/TITLE"

    raw_feature_coverage: float = 0.0
    weighted_technical_score: float = 0.0
    matched_feature_count: int = 0
    total_feature_count: int = 0
    claims_status: str = "NOT_AVAILABLE"
    full_text_status: str = "NOT_AVAILABLE"
    has_abstract: bool = True
    has_claims: bool = False
    has_description: bool = False
    has_full_text: bool = False
    score_cap: Optional[float] = None
    score_cap_reason: Optional[str] = None
    verification_status: str = "NOT_VERIFIED"
    data_quality_status: str = "LIMITED"

    # 4 Separated Conclusions
    technical_relevance_conclusion: str = "Evaluated technical feature disclosure overlap against prior art."
    evidence_confidence_conclusion: str = "Evidence confidence based on text quote verification."
    temporal_status_conclusion: str = "Timeline status relative to user reference date."
    legal_assessment_disclaimer: str = (
        "Preliminary AI screening only. Legal patentability is not determined by AI and requires formal patent attorney examination."
    )



class SearchSummary(BaseModel):
    total_results: int
    high_similarity: int
    moderate_similarity: int
    low_similarity: int
    very_high_similarity: int
    patents_searched: Optional[int] = 0
    patents_retrieved: Optional[int] = 0
    patents_shortlisted: Optional[int] = 0
    patents_deeply_analyzed: Optional[int] = 0
    highest_semantic_similarity: Optional[float] = 0.0
    unique_families_count: Optional[int] = 0
    pipeline_metrics: Optional[PipelineMetrics] = None


class PriorArtSearchResponse(BaseModel):
    search_id: str
    invention_title: str
    domain: str
    created_at: datetime
    risk_level: str
    risk_label: str
    highest_similarity: float
    highest_semantic_similarity: Optional[float] = 0.0
    summary: SearchSummary
    results: List[SearchResultItem]
    ai_analysis: Optional[Dict[str, Any]] = None
    is_demo_dataset: bool = True
    data_source: Optional[str] = "Live arXiv Feed"
    ai_model_used: Optional[str] = "Gemini 2.5 Flash"
    disclaimer: str = (
        "PatentLens AI provides AI-assisted preliminary technical prior-art relevance analysis. "
        "Results are intended for research and screening purposes and do not constitute a legal opinion "
        "or definitive patentability determination. Professional patent review is recommended before filing or making legal decisions."
    )


class SearchHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    invention_title: str
    domain: str
    created_at: datetime
    highest_similarity: float
    risk_level: str
    total_results: int = 0


# --- Saved Patents Schemas ---

class SavePatentRequest(BaseModel):
    notes: Optional[str] = None


class SavedPatentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patent_id: str
    notes: Optional[str] = None
    created_at: datetime
    patent: PatentOut


# --- Report Schemas ---

class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    search_id: str
    report_path: str
    created_at: datetime
