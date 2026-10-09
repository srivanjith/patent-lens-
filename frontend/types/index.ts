export interface User {
  id: string;
  name: string;
  email: string;
  is_verified?: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  token_type?: string;
  require_otp?: boolean;
  otp_sent_to?: string;
  demo_otp?: string;
  user?: User;
}

export interface Patent {
  id: string;
  patent_number: string;
  title: string;
  abstract: string;
  description: string;
  claims?: string;
  inventors: string;
  assignee: string;
  publication_date: string;
  domain: string;
  source_url?: string;
  source_type?: string;
  source_status?: string;
  document_type?: string;
  cpc_codes?: string;
  jurisdiction?: string;
}

export interface FeatureComparisonItem {
  target_feature: string;
  prior_art_feature: string;
  match_level: 'Strong' | 'Partial' | 'Weak' | 'Not Found';
  explanation: string;
  evidence_quote?: string;
  confidence?: number;
}

export interface ClaimElementItem {
  limitation_number: number;
  element_text: string;
  status: 'EXPLICIT' | 'INHERENT' | 'PARTIAL' | 'NOT_DISCLOSED';
  evidence_quote: string;
  explanation: string;
}

export interface ComponentBreakdownItem {
  value?: number | null;
  weight: number;
  effective_weight: number;
  contribution: number;
  status: 'AVAILABLE' | 'UNAVAILABLE';
}

export interface ScoreBreakdown {
  semantic?: ComponentBreakdownItem;
  technical_features?: ComponentBreakdownItem;
  evidence?: ComponentBreakdownItem;
  concepts?: ComponentBreakdownItem;
  domain_cpc?: ComponentBreakdownItem;
  semantic_similarity: number;
  technical_features_score?: number;
  evidence_strength: number;
  distinctive_concepts: number;
  domain_cpc_alignment: number;
  technology_domain_score?: number;
  cpc_match_score?: number;
  final_score: number;
  confidence_score?: number;
  calculation_method?: string;
  is_gated: boolean;
  score_cap?: number | null;
  score_cap_reason?: string | null;
  formula_explanation: string;
}

export interface PatentFamilyMember {
  patent_number: string;
  jurisdiction: string;
  kind?: string;
  title: string;
  publication_date: string;
  document_type: string;
  source_url: string;
}

export interface PipelineMetrics {
  patents_searched: number;
  patents_retrieved: number;
  vector_shortlisted: number;
  final_shortlisted?: number;
  unique_families: number;
  semantic_candidates?: number;
  technical_candidates?: number;
  patents_with_claims: number;
  patents_with_full_text: number;
  evidence_verified_matches: number;
  lens_api_status?: string;
}

export interface EvidenceItem {
  feature: string;
  status: 'verified' | 'unverified' | 'limited';
  similarity: number;
  evidence: string;
  source: string;
  verified: boolean;
}

export interface SearchResultItem {
  confidence_score?: number;
  legal_assessment_disclaimer?: string;
  evidence_confidence_conclusion?: string;
  temporal_status_conclusion?: string;
  technical_relevance_conclusion?: string;
  patent: Patent;
  semantic_score: number;
  keyword_score: number;
  domain_score: number;
  final_score: number;
  matched_concepts: string[];
  rank: number;
  semantic_similarity_label?: string;
  relevance_explanation?: string;
  feature_comparison?: FeatureComparisonItem[];
  patent_specific_insights?: string[];
  technical_features?: string[];
  distinctive_features?: string[];
  matched_features?: any[];
  strong_matches?: string[];
  partial_matches?: string[];
  missing_features?: string[];
  unmatched_features?: string[];
  evidence_items?: EvidenceItem[];
  evidence_status_label?: string;
  claim_elements?: ClaimElementItem[];
  single_document_anticipation?: 'YES' | 'NO';
  missing_elements?: string[];
  technical_feature_coverage?: number;
  evidence_confidence?: number;
  overall_result?: 'ANTICIPATED' | 'NON_ANTICIPATED';
  score_breakdown?: ScoreBreakdown;
  family_members?: PatentFamilyMember[];
  family_size?: number;
  is_family_representative?: boolean;
  family_id?: string;
  temporal_status?: 'BEFORE_REFERENCE_DATE' | 'AFTER_REFERENCE_DATE' | 'DATE_UNKNOWN' | string;
  result_status?: string;
  relevance_level?: string;
  evidence_status?: 'VERIFIED' | 'PARTIAL' | 'NOT_VERIFIED' | 'NOT_AVAILABLE' | 'UNAVAILABLE' | string;
  source_status?: string;
  source_name?: string;
  source_type?: string;
  retrieval_status?: string;
  raw_feature_coverage?: number;
  weighted_technical_score?: number;
  matched_feature_count?: number;
  total_feature_count?: number;
  claims_status?: 'AVAILABLE' | 'NOT_AVAILABLE';
  full_text_status?: 'AVAILABLE' | 'NOT_AVAILABLE';
  score_cap?: number;
  score_cap_reason?: string;
}

export interface SearchSummary {
  total_results: number;
  high_similarity: number;
  moderate_similarity: number;
  low_similarity: number;
  very_high_similarity: number;
  patents_searched?: number;
  patents_retrieved?: number;
  patents_shortlisted?: number;
  patents_deeply_analyzed?: number;
  highest_semantic_similarity?: number;
  unique_families_count?: number;
  pipeline_metrics?: PipelineMetrics;
}

export interface PriorArtSearchResponse {
  search_id: string;
  invention_title: string;
  domain: string;
  created_at: string;
  risk_level: 'LOW' | 'MODERATE' | 'HIGH' | 'VERY HIGH';
  risk_label: string;
  highest_similarity: number;
  highest_semantic_similarity?: number;
  summary: SearchSummary;
  results: SearchResultItem[];
  is_demo_dataset: boolean;
  data_source?: string;
  ai_model_used?: string;
  disclaimer: string;
}

export interface SearchHistoryItem {
  id: string;
  invention_title: string;
  domain: string;
  created_at: string;
  highest_similarity: number;
  risk_level: 'LOW' | 'MODERATE' | 'HIGH' | 'VERY HIGH';
  total_results: number;
}

export interface SavedPatent {
  id: string;
  patent_id: string;
  notes?: string;
  created_at: string;
  patent: Patent;
}

export interface Report {
  id: string;
  search_id: string;
  report_path: string;
  created_at: string;
}

export interface SearchFormData {
  title: string;
  domain: string;
  problem_statement: string;
  description: string;
  keywords: string[];
  reference_date?: string;
}
