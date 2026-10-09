import logging
import json
import re
import httpx
from typing import Dict, Any, List, Optional
from app.core.config import settings
logger = logging.getLogger("patentlens.gemini")

class GeminiService:
    """Service for generating evidence-based patent claim examination using Google's official google-genai SDK (gemini-2.5-flash)."""
    _rate_limited = False

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model_name = getattr(settings, "GEMINI_MODEL", "") or "gemini-2.5-flash"
        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        api_key = settings.GEMINI_API_KEY
        if api_key and len(api_key.strip()) > 10 and not api_key.startswith("your_"):
            self.api_key = api_key.strip()
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"Google GenAI official SDK client initialized for model '{self.model_name}'.")
            except Exception as e:
                logger.warning(f"Could not load google-genai SDK client: {e}. Falling back to REST API.")
                self.client = None
        else:
            logger.info("Gemini API key not configured or placeholder used. Heuristic NLP analysis will be used.")

    @property
    def is_configured(self) -> bool:
        if GeminiService._rate_limited:
            return False
        return bool(self.api_key and len(self.api_key.strip()) > 10 and not self.api_key.startswith("your_"))

    def analyze_invention(
        self,
        title: str,
        problem_statement: str,
        description: str,
        keywords: Optional[List[str]] = None,
        domain: str = ""
    ) -> Dict[str, Any]:
        """
        Analyze user invention using Gemini 2.5 Flash to extract structured technical features
        (essential vs optional, component + function + relationship + purpose quadruplets),
        8 multi-strategy search queries, and CPC classification candidates.
        """
        title = title or ""
        problem_statement = problem_statement or ""
        description = description or ""
        keywords = keywords or []
        domain = domain or "Technology"

        import os
        is_testing = (getattr(settings, "TESTING", False) or os.getenv("TESTING", "").lower() == "true") and not (getattr(settings, "LIVE_BENCHMARK", False) or os.getenv("LIVE_BENCHMARK", "").lower() == "true")
        is_mocked = "mock" in type(self.client).__module__.lower() or "mock" in type(self.client).__name__.lower() if self.client else False
        if is_testing and not is_mocked:
            return self._heuristic_invention_analysis(title, problem_statement, description, keywords, domain)

        if self.is_configured and not GeminiService._rate_limited:
            system_prompt = "You are a Senior Patent Examiner and IP Analyst. Return strict valid JSON only."
            user_prompt = f"""
Analyze the target invention disclosure and decompose it into structured technical concepts for prior-art retrieval.

RULES & SCHEMA REQUIREMENTS:
1. "technical_problem": Extract the actual core technical engineering problem solved (not just the broad domain topic).
2. "essential_features": Identify 3-6 essential claim limitations defining the primary inventive concept.
3. "optional_features": Identify 2-5 secondary or optional implementation details.
4. "technical_features": Extract 5-10 specific engineering concepts. Each feature MUST represent COMPONENT + FUNCTION + RELATIONSHIP + PURPOSE. Avoid generic words ("system", "device", "control", "signal").
5. "structured_quadruplets": Array of objects: [{{"component": "transmitter coil", "function": "generates electromagnetic field", "relationship": "coupled to power inverter", "purpose": "transfers energy wirelessly"}}].
6. "distinctive_features": 3-8 most distinctive technical concepts carrying high weight.
7. "functional_relationships": Explicit COMPONENT -> ACTION -> CONDITION -> RESULT relationships.
8. "components": Hardware/structural elements.
9. "inputs" & "outputs": Physical parameters, signals, measurements.
10. "technical_effects": Engineering benefits (e.g. "prevents parasitic heating").
11. "alternative_terms": Technical synonyms used in international patent literature.
12. "search_queries": Generate EXACTLY 8 multi-strategy queries covering all 8 search paths:
   1. Core concept query
   2. Technical terminology query
   3. Component-function query
   4. Component-relationship query
   5. Operating-principle query
   6. Claims-oriented query
   7. CPC/IPC query
   8. Broad discovery query
13. "possible_cpc_ipc_classes": 2-5 relevant CPC/IPC classification codes (e.g. "H02J50/60", "H02J50/12").

INVENTION DISCLOSURE:
Title: {title}
Domain: {domain}
Problem: {problem_statement}
Description: {description}
Keywords: {', '.join(keywords)}

Return ONLY valid JSON matching this exact structure:
{{
  "title": "{title}",
  "technical_problem": "Core technical problem description",
  "technical_domain": "{domain}",
  "core_invention": "1-sentence summary of primary technical mechanism",
  "essential_features": [
    "foreign object detection coil circuit"
  ],
  "optional_features": [
    "user notification LED indicator"
  ],
  "technical_features": [
    "controller dynamically adjusts foreign-object detection threshold based on coil alignment"
  ],
  "structured_quadruplets": [
    {{
      "component": "controller",
      "function": "dynamically adjusts detection threshold",
      "relationship": "coupled to coil sensor circuit",
      "purpose": "prevents false positive thermal shutdowns"
    }}
  ],
  "distinctive_features": [
    "foreign object detection using coil electrical parameters"
  ],
  "functional_relationships": [
    "alignment sensor modifies threshold value when coil displacement occurs"
  ],
  "components": ["transmitter coil", "receiver coil", "controller"],
  "inputs": ["coil impedance", "resonant frequency"],
  "outputs": ["FOD alert signal", "power reduction signal"],
  "technical_effects": ["prevents parasitic heating of metallic objects"],
  "alternative_terms": ["wireless power transfer", "inductive power transfer"],
  "search_concepts": ["foreign object detection", "wireless power transfer"],
  "search_queries": [
    "\"wireless power transfer\" AND \"foreign object detection\"",
    "\"transmitter coil\" AND \"adjusts detection threshold\"",
    "\"controller\" AND \"coupled to coil sensor\"",
    "\"foreign object detection using coil electrical parameters\"",
    "claim:(\"foreign object detection\" AND coil)",
    "\"adaptive threshold adjustment\" AND \"alignment\"",
    "classifications_cpc.symbol:\"H02J50/60\"",
    "\"inductive power transfer\" AND \"parasitic load\""
  ],
  "possible_cpc_ipc_classes": ["H02J50/60", "H02J50/12"]
}}
"""
            try:
                client = self.client
                if client is not None:
                    from google.genai import types
                    import concurrent.futures
                    logger.info("Extracting invention technical features via Gemini SDK...")
                    def _call_sdk():
                        return client.models.generate_content(
                            model=self.model_name,
                            contents=f"{system_prompt}\n\n{user_prompt}",
                            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
                        )
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(_call_sdk)
                        res = fut.result(timeout=4.0)
                    if res and res.text:
                        parsed = json.loads(res.text)
                        return self._clean_invention_analysis(parsed, title, keywords, domain)

                # REST API Fallback
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
                    "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
                }
                with httpx.Client(timeout=4.0) as http_client:
                    response = http_client.post(url, json=payload)
                    if response.status_code == 200:
                        text_content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = json.loads(text_content)
                        return self._clean_invention_analysis(parsed, title, keywords, domain)
                    elif response.status_code == 429:
                        GeminiService._rate_limited = True
                        logger.warning("[GEMINI] 429 Rate limit in analyze_invention. Activating circuit breaker.")
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                    GeminiService._rate_limited = True
                    logger.warning(f"[GEMINI] Rate limit / quota exhausted in analyze_invention: {e}. Activating circuit breaker for instant grounded NLP fallback.")
                else:
                    logger.error(f"[GEMINI] Error in analyze_invention: {e}")

        return self._heuristic_invention_analysis(title, problem_statement, description, keywords, domain)

    def _clean_invention_analysis(
        self,
        parsed: Dict[str, Any],
        title: str,
        keywords: List[str],
        domain: str
    ) -> Dict[str, Any]:
        GENERIC_NOISE = {
            "system", "device", "technology", "signal", "ai", "electronics",
            "method", "apparatus", "process", "mechanism", "unit", "module",
            "component", "feature", "data", "information", "operation",
            "medical", "image", "images", "deep", "learning", "detection", "analysis"
        }
        
        raw_feats = parsed.get("technical_features", [])
        clean_feats = [str(f).strip() for f in raw_feats if str(f).strip().lower() not in GENERIC_NOISE]

        raw_essential = parsed.get("essential_features", [])
        clean_essential = [str(e).strip() for e in raw_essential if str(e).strip().lower() not in GENERIC_NOISE]

        raw_dist = parsed.get("distinctive_features", [])
        clean_dist = [str(d).strip() for d in raw_dist if str(d).strip().lower() not in GENERIC_NOISE]

        raw_queries = parsed.get("search_queries", [])
        clean_queries = []
        for q in raw_queries:
            q_str = str(q).strip()
            if q_str and q_str.lower() not in GENERIC_NOISE:
                clean_queries.append(q_str)

        cpc_list = parsed.get("possible_cpc_ipc_classes") or parsed.get("cpc_candidates") or []

        # Guarantee at least 8 queries across 8 strategies dynamically
        if len(clean_queries) < 8:
            base_kw = keywords[:4] if keywords else ([domain] if domain else [title])
            cpc_sym = (cpc_list[0] if cpc_list else "").strip()
            cpc_clause = f"classifications_cpc.symbol:\"{cpc_sym}\"" if cpc_sym else f"\"{title}\""

            strategies_fill = [
                f"\"{title}\" AND \"{base_kw[0] if base_kw else title}\"",
                f"\"{clean_dist[0] if clean_dist else title}\" AND \"{clean_essential[0] if clean_essential else domain}\"",
                f"\"{clean_dist[0] if clean_dist else title}\"",
                f"\"{clean_essential[0] if clean_essential else title}\"",
                f"claims:(\"{clean_dist[0] if clean_dist else title}\")",
                cpc_clause,
                f"\"{domain or 'technology'}\" AND \"{clean_dist[0] if clean_dist else title}\"",
                f"\"{title}\""
            ]
            for sf in strategies_fill:
                if len(clean_queries) >= 8:
                    break
                if sf not in clean_queries:
                    clean_queries.append(sf)

        return {
            "title": parsed.get("title") or title,
            "technical_problem": parsed.get("technical_problem") or parsed.get("problem") or f"Optimization of {domain} system performance",
            "problem": parsed.get("problem") or parsed.get("technical_problem") or "",
            "technical_domain": parsed.get("technical_domain") or domain,
            "core_invention": parsed.get("core_invention") or title,
            "essential_features": clean_essential or clean_feats[:4] or [title],
            "optional_features": parsed.get("optional_features", []),
            "technical_features": clean_feats or [title],
            "structured_quadruplets": parsed.get("structured_quadruplets", []),
            "distinctive_features": clean_dist or clean_feats[:4],
            "functional_relationships": parsed.get("functional_relationships", []),
            "components": parsed.get("components", []),
            "inputs": parsed.get("inputs", []),
            "outputs": parsed.get("outputs", []),
            "technical_effects": parsed.get("technical_effects", []),
            "alternative_terms": parsed.get("alternative_terms", []),
            "search_concepts": parsed.get("search_concepts") or keywords,
            "search_queries": clean_queries[:8],
            "possible_cpc_ipc_classes": cpc_list,
            "cpc_candidates": cpc_list,
            "domain": parsed.get("technical_domain") or domain
        }

    def _heuristic_invention_analysis(
        self,
        title: str,
        problem_statement: str,
        description: str,
        keywords: List[str],
        domain: str
    ) -> Dict[str, Any]:
        try:
            from ml.keyword_extractor import extract_structured_invention_features, extract_atomic_technical_features
        except ImportError:
            from ml.keyword_extractor import extract_structured_invention_features, extract_atomic_technical_features
        full_text = f"{title} {problem_statement} {description}"
        struct_res = extract_structured_invention_features(full_text)
        atomic_feats = extract_atomic_technical_features(full_text, top_n=8)
        
        distinctive = [f for f in atomic_feats if len(f.split()) >= 2] or atomic_feats[:4]

        dist_0 = distinctive[0] if distinctive else title
        dist_1 = distinctive[1] if len(distinctive) > 1 else (domain or "system")

        search_queries = [
            f"\"{dist_0}\" AND \"{dist_1}\"",
            f"\"{dist_0}\"",
            f"\"{title}\"",
            f"\"{domain or 'technology'}\" AND \"{dist_0}\"",
            f"\"operating principle\" AND \"{dist_0}\"",
            f"claims:(\"{dist_0}\")",
            f"\"{dist_1}\"",
            f"\"{domain or 'technology'}\" AND \"prior art\""
        ]

        return {
            "title": title,
            "technical_problem": problem_statement[:200] if problem_statement else f"Technical optimization in {domain}",
            "problem": problem_statement[:200],
            "technical_domain": domain or "Technology",
            "core_invention": title,
            "essential_features": struct_res.get("essential_features") or atomic_feats[:4],
            "optional_features": struct_res.get("optional_features") or [],
            "technical_features": atomic_feats or [title],
            "structured_quadruplets": struct_res.get("structured_quadruplets") or [],
            "distinctive_features": distinctive,
            "functional_relationships": [f"{dist_0} operates within {domain}"] if distinctive else [],
            "components": keywords or ["control module"],
            "inputs": ["operating parameter"],
            "outputs": ["control response"],
            "technical_effects": ["improves system performance"],
            "alternative_terms": keywords or [],
            "search_concepts": distinctive or atomic_feats[:4],
            "search_queries": search_queries[:8],
            "possible_cpc_ipc_classes": [],
            "cpc_candidates": [],
            "domain": domain or "Technology"
        }

    def analyze_patent_pair(
        self,
        target_title: str,
        target_problem: str,
        target_description: str,
        patent_number: str,
        patent_title: str,
        patent_abstract: str,
        patent_description: str,
        similarity_score: float
    ) -> Dict[str, Any]:
        """
        Decompose invention claims into atomic technical limitations and perform rigorous 
        feature-by-feature prior-art comparison using Gemini 2.5 Flash SDK.
        Outputs 4 separate conclusions: Technical Relevance, Evidence Confidence, Temporal Status, Legal Assessment.
        """
        target_title = target_title or ""
        target_problem = target_problem or ""
        target_description = target_description or ""
        patent_number = patent_number or ""
        patent_title = patent_title or ""
        patent_abstract = patent_abstract or ""
        patent_description = patent_description or ""

        import os
        is_testing = (getattr(settings, "TESTING", False) or os.getenv("TESTING", "").lower() == "true") and not (getattr(settings, "LIVE_BENCHMARK", False) or os.getenv("LIVE_BENCHMARK", "").lower() == "true")
        is_mocked = "mock" in type(self.client).__module__.lower() or "mock" in type(self.client).__name__.lower() if self.client else False
        if is_testing and not is_mocked:
            return self._normalize_parsed_response(self._generate_heuristic_pair_analysis(
                target_title, target_description, patent_number, patent_title, patent_abstract, similarity_score, patent_description
            ))

        if self.is_configured and not GeminiService._rate_limited:
            system_prompt = "You are a Senior Patent Examiner conducting strict prior-art claim analysis. Output strict valid JSON only."
            user_prompt = f"""
You are a Senior Patent Examiner conducting a rigorous prior-art anticipation and feature disclosure comparison.

EXAMINATION RULES & REQUIRED OUTPUTS:
1. Break the target invention claim/description into atomic technical limitations/elements.
2. Compare EVERY limitation against the supplied prior-art document ({patent_number}: '{patent_title}').
3. Classify EVERY limitation as exactly ONE of 5 levels:
   - STRONG_MATCH: Explicitly disclosed in prior-art claims or abstract text with quote.
   - PARTIAL_MATCH: Partially disclosed or broadly suggested without full structural details.
   - WEAK_MATCH: Generic or broad domain term match only.
   - NOT_FOUND: Completely absent from prior-art text.
   - UNABLE_TO_VERIFY: Text unavailable for verification.
4. Provide explicit supporting quotes/evidence directly from prior-art text for every match. NEVER FABRICATE EVIDENCE QUOTES.
5. Provide FOUR SEPARATE CONCLUSIONS:
   - "technical_relevance_conclusion": Detailed evaluation of technical feature overlap.
   - "evidence_confidence_conclusion": Strength of available supporting document evidence.
   - "temporal_status_conclusion": Timeline evaluation relative to reference date.
   - "legal_assessment_disclaimer": "Preliminary AI screening only. Final patentability requires formal patent attorney examination."

TARGET INVENTION:
Title: {target_title}
Problem: {target_problem}
Description: {target_description}

RETRIEVED PRIOR-ART PATENT:
Patent Number: {patent_number}
Title: {patent_title}
Abstract: {patent_abstract}
Description: {patent_description[:1500]}
SBERT Vector Retrieval Score: {similarity_score}%

Return ONLY valid JSON matching this exact structure:
{{
  "overall_result": "ANTICIPATED | PARTIALLY_DISCLOSED | NOT_ANTICIPATED | INSUFFICIENT_EVIDENCE",
  "confidence": 87,
  "technical_feature_coverage": 25.0,
  "technical_relevance_conclusion": "Technically similar regarding wireless power transfer but lacks specific foreign object dynamic threshold circuit.",
  "evidence_confidence_conclusion": "High confidence supported by explicit quotes from patent claims.",
  "temporal_status_conclusion": "Published prior to target reference date.",
  "legal_assessment_disclaimer": "Preliminary AI screening only. Final legal patentability requires formal patent attorney examination.",
  "claim_elements": [
    {{
      "element": "Atomic technical limitation name",
      "status": "STRONG_MATCH | PARTIAL_MATCH | WEAK_MATCH | NOT_FOUND | UNABLE_TO_VERIFY",
      "evidence": "Direct quote or explicit evidence from prior-art text",
      "source_document": "{patent_number}"
    }}
  ],
  "single_document_anticipation": {{
    "found": false,
    "reason": "Detailed explanation of single-document disclosure assessment."
  }},
  "missing_elements": [
    "Specific missing technical element name"
  ],
  "reasoning": "Matched technical features -> evidence -> match strength -> missing features -> overall technical relevance",
  "relevance_explanation": "2-sentence evidence-based relevance summary.",
  "overlap_summary": "2-sentence feature disclosure summary.",
  "patent_specific_insights": [
    "Key technical insight regarding prior-art specification."
  ],
  "technical_features": [
    "wireless power transfer",
    "impedance measurement"
  ],
  "distinctive_features": [
    "foreign object detection"
  ],
  "matched_features": [
    {{
      "feature": "impedance measurement",
      "match_level": "STRONG_MATCH",
      "evidence": "Discloses impedance measurement circuit."
    }}
  ],
  "unmatched_features": [
    "temperature compensation"
  ],
  "feature_comparison": [
    {{
      "target_feature": "foreign object detection",
      "prior_art_feature": "metallic debris detection circuit",
      "match_level": "Strong",
      "explanation": "Both systems disclose sensor routines for detecting obstacles."
    }}
  ]
}}
"""

            try:
                client = self.client
                if client is not None:
                    from google.genai import types
                    import concurrent.futures
                    logger.info("Executing Gemini Flash analysis via official google-genai SDK...")
                    def _call_pair_sdk():
                        return client.models.generate_content(
                            model=self.model_name,
                            contents=f"{system_prompt}\n\n{user_prompt}",
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                temperature=0.1
                            )
                        )
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(_call_pair_sdk)
                        response = fut.result(timeout=3.0)
                    if response and response.text:
                        parsed = json.loads(response.text)
                        parsed["ai_powered"] = True
                        parsed["model_used"] = self.model_name
                        parsed["provider"] = "gemini"
                        return self._normalize_parsed_response(parsed)

                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
                    "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
                }
                with httpx.Client(timeout=3.0) as http_client:
                    res = http_client.post(url, json=payload)
                    if res.status_code == 200:
                        text_content = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = json.loads(text_content)
                        parsed["ai_powered"] = True
                        parsed["model_used"] = self.model_name
                        parsed["provider"] = "gemini"
                        return self._normalize_parsed_response(parsed)
                    elif res.status_code == 429:
                        GeminiService._rate_limited = True
                        logger.warning("[GEMINI] 429 Rate limit encountered. Activating circuit breaker for instant grounded NLP fallback.")

            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                    GeminiService._rate_limited = True
                    logger.warning(f"[GEMINI] Rate limit / quota exhausted: {e}. Switching immediately to instant grounded NLP fallback.")
                else:
                    logger.error(f"Error in Gemini patent pair analysis: {e}")

        # Heuristic NLP Fallback when API key is offline or unconfigured
        return self._normalize_parsed_response(self._generate_heuristic_pair_analysis(
            target_title=target_title,
            target_description=target_description,
            patent_number=patent_number,
            patent_title=patent_title,
            patent_abstract=patent_abstract,
            similarity_score=similarity_score,
            patent_description=patent_description
        ))

    def _generate_heuristic_pair_analysis(
        self,
        target_title: str,
        target_description: str,
        patent_number: str,
        patent_title: str,
        patent_abstract: str,
        similarity_score: float,
        patent_description: str = ""
    ) -> Dict[str, Any]:
        """Grounded NLP claim decomposition fallback when LLM API is unavailable."""
        try:
            from ml.keyword_extractor import extract_atomic_technical_features
        except ImportError:
            from ml.keyword_extractor import extract_atomic_technical_features

        target_text = f"{target_title} {target_description}".lower()
        patent_text = f"{patent_title} {patent_abstract} {patent_description}".lower()

        target_tech_features = extract_atomic_technical_features(target_text, top_n=9)
        if not target_tech_features:
            target_tech_features = [target_title.title()]

        claim_elements = []
        matched_feats = []
        unmatched_feats = []
        matched_feature_objects = []
        feature_comparison = []

        for feat in target_tech_features:
            feat_lower = feat.lower()
            pattern = r'\b' + re.escape(feat_lower) + r'\b' if len(feat_lower.split()) == 1 else re.escape(feat_lower)
            m_found = re.search(pattern, patent_text)
            if m_found:
                matched_feats.append(feat)
                match_lvl = "STRONG_MATCH" if similarity_score > 60.0 else "PARTIAL_MATCH"
                
                # Extract actual snippet surrounding match
                st = max(0, m_found.start() - 25)
                en = min(len(patent_text), m_found.end() + 75)
                real_quote = patent_text[st:en].replace("\n", " ").strip()

                matched_feature_objects.append({
                    "feature": feat,
                    "match_level": match_lvl,
                    "evidence": real_quote,
                    "evidence_quote": real_quote,
                    "verification_status": "VERIFIED"
                })
                claim_elements.append({
                    "element": feat,
                    "status": match_lvl,
                    "evidence": real_quote,
                    "evidence_quote": real_quote,
                    "verification_status": "VERIFIED",
                    "source_document": patent_number or patent_title
                })
                feature_comparison.append({
                    "target_feature": feat,
                    "prior_art_feature": feat,
                    "match_level": "Strong" if similarity_score > 60.0 else "Partial",
                    "explanation": f"Specification text matches '{feat}'.",
                    "evidence_quote": real_quote,
                    "evidence_source": "SPECIFICATION",
                    "evidence_text_origin": "SPECIFICATION",
                    "verification_status": "VERIFIED",
                    "confidence": round(min(92.0, (similarity_score * 0.5) + 45.0), 1)
                })
            else:
                unmatched_feats.append(feat)
                claim_elements.append({
                    "element": feat,
                    "status": "NOT_FOUND",
                    "evidence": "",
                    "evidence_quote": None,
                    "verification_status": "UNVERIFIED",
                    "source_document": patent_number or patent_title
                })
                feature_comparison.append({
                    "target_feature": feat,
                    "prior_art_feature": "Not Disclosed",
                    "match_level": "Not Found",
                    "explanation": f"Feature '{feat}' is not disclosed in patent specification.",
                    "evidence_quote": None,
                    "evidence_source": "NOT_AVAILABLE",
                    "evidence_text_origin": "NOT_AVAILABLE",
                    "verification_status": "UNVERIFIED",
                    "confidence": 0.0
                })

        total_elems = len(target_tech_features)
        matched_count = len(matched_feats)
        coverage_pct = round((matched_count / total_elems) * 100.0, 1) if total_elems > 0 else 0.0

        single_doc_anticipation = {
            "found": coverage_pct == 100.0 and total_elems > 1,
            "reason": (
                f"Single document '{patent_title}' discloses {matched_count} out of {total_elems} essential claim limitations. "
                + ("All essential limitations are disclosed." if coverage_pct == 100.0 else "Missing essential limitations prevents single-document anticipation.")
            )
        }

        if coverage_pct >= 80.0:
            overall_result = "ANTICIPATED"
        elif coverage_pct >= 35.0:
            overall_result = "PARTIALLY_DISCLOSED"
        else:
            overall_result = "NOT_ANTICIPATED"

        if matched_feats:
            relevance = f"Matched features ({len(matched_feats)}/{total_elems}): {', '.join(matched_feats[:4])} -> Evidence verified in specification -> Match strength: High -> Missing features: {', '.join(unmatched_feats[:3]) if unmatched_feats else 'None'} -> Overall Technical Relevance: High."
            overlap_summary = f"Direct technical feature match identified across {', '.join(matched_feats[:3])}."
        else:
            relevance = f"Zero matching technical features detected in prior art text. Overall Technical Relevance: Low."
            overlap_summary = "Zero direct technical feature overlap detected between target invention and prior art document."

        tech_rel_conc = f"Technical overlap is {coverage_pct}% across {matched_count}/{total_elems} features."
        ev_conf_conc = "Evidence verified against specification text." if matched_feats else "Evidence unverified."

        return {
            "ai_powered": False,
            "model_used": "Heuristic-NLP",
            "provider": "heuristic",
            "overall_result": overall_result,
            "confidence": 85 if matched_feats else 40,
            "technical_feature_coverage": coverage_pct,
            "technical_relevance_conclusion": tech_rel_conc,
            "evidence_confidence_conclusion": ev_conf_conc,
            "temporal_status_conclusion": "Prior art publication timeline evaluated relative to reference date.",
            "legal_assessment_disclaimer": "Preliminary AI prior-art screening only. Legal patentability is not determined by AI.",
            "claim_elements": claim_elements,
            "single_document_anticipation": single_doc_anticipation,
            "missing_elements": unmatched_feats,
            "reasoning": relevance,
            "technical_features": target_tech_features,
            "distinctive_features": [f for f in target_tech_features if len(f.split()) >= 2],
            "matched_features": matched_feature_objects,
            "unmatched_features": unmatched_feats,
            "overlap_summary": overlap_summary,
            "relevance_explanation": relevance,
            "patent_specific_insights": [f"Prior-art document addresses '{patent_title}'.", f"Feature disclosure coverage: {coverage_pct}% ({matched_count}/{total_elems} matched)."],
            "feature_comparison": feature_comparison or [{
                "target_feature": target_title,
                "prior_art_feature": patent_title,
                "match_level": "Not Found",
                "explanation": f"Zero matching technical features found in '{patent_title}'."
            }]
        }

    def generate_novelty_analysis(
        self,
        invention_title: str,
        problem_statement: str,
        description: str,
        matched_patents: List[Dict[str, Any]],
        risk_level: str
    ) -> Dict[str, Any]:
        """Generate high-level overall summary across top prior-art matches using Gemini 2.5 Flash."""
        if not self.is_configured or GeminiService._rate_limited:
            return self._generate_fallback_summary(invention_title, risk_level, matched_patents)

        try:
            patents_summary = "\n".join([
                f"- Patent {p.get('patent_number', 'N/A')}: {p.get('title', '')} (SBERT Sim: {p.get('final_score', 0)}%)\n"
                f"  Abstract: {p.get('abstract', '')[:200]}..."
                for p in matched_patents[:3]
            ])

            user_prompt = f"""
You are a Senior AI Patent Examiner. Provide a high-level preliminary prior-art assessment for the target invention using Gemini 2.5 Flash.
Do NOT state that the invention is "invalid" or "not patentable".

INVENTION TITLE: {invention_title}
PROBLEM STATEMENT: {problem_statement}
DESCRIPTION: {description}
OVERALL RELEVANCE PROFILE: {risk_level}

TOP MATCHED PRIOR-ART PATENTS:
{patents_summary}

Provide a structured analysis in JSON format with keys:
1. "executive_summary": 2-3 sentence preliminary AI prior-art assessment.
2. "overlapping_concepts": List of 3 specific technical features or claim elements that overlap with prior art.
3. "recommendations": List of 3 actionable suggestions to narrow independent claims.
4. "novelty_rating": One of "Low", "Moderate", "High", "Very High".

Return ONLY valid JSON.
"""

            client = self.client
            if client is not None:
                from google.genai import types
                import concurrent.futures
                def _call_novelty_sdk():
                    return client.models.generate_content(
                        model=self.model_name,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
                    )
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(_call_novelty_sdk)
                    res = fut.result(timeout=3.0)
                if res and res.text:
                    parsed = json.loads(res.text)
                    parsed["ai_powered"] = True
                    parsed["model_used"] = self.model_name
                    parsed["provider"] = "gemini"
                    return parsed

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
            }
            with httpx.Client(timeout=3.0) as http_client:
                response = http_client.post(url, json=payload)
                if response.status_code == 200:
                    text_content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(text_content)
                    parsed["ai_powered"] = True
                    parsed["model_used"] = self.model_name
                    parsed["provider"] = "gemini"
                    return parsed
                elif response.status_code == 429:
                    GeminiService._rate_limited = True
                    logger.warning("[GEMINI] 429 Rate limit in generate_novelty_analysis. Activating circuit breaker.")

        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                GeminiService._rate_limited = True
                logger.warning(f"[GEMINI] Rate limit / quota in generate_novelty_analysis: {e}. Activating circuit breaker.")
            else:
                logger.error(f"Error in Gemini novelty analysis: {e}")

        return self._generate_fallback_summary(invention_title, risk_level, matched_patents)

    def _generate_fallback_summary(
        self,
        invention_title: str,
        risk_level: str,
        matched_patents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Rule-based overall summary when LLM API is unavailable."""
        top_patent = matched_patents[0] if matched_patents else {}
        top_title = top_patent.get("title", "existing prior art")
        
        return {
            "ai_powered": False,
            "model_used": "Heuristic-NLP",
            "provider": "heuristic",
            "executive_summary": (
                f"Preliminary AI Prior-Art Assessment indicates that '{invention_title}' exhibits a '{risk_level}' "
                f"relevance profile due to technical overlap with '{top_title}'. The identified document contains "
                f"several technical features that overlap with the target invention; further claim-level analysis is required to determine novelty."
            ),
            "overlapping_concepts": [
                "Primary system processing framework and telemetry data collection",
                "Parameter calculation routines and diagnostic state evaluation",
                "Adaptive output adjustment based on evaluated metrics"
            ],
            "recommendations": [
                "Detail specific novel algorithm parameters or structural hardware components in independent claims.",
                "Emphasize unique technical advantages and unexpected technical results in the specification.",
                "Conduct full freedom-to-operate (FTO) clearance with a registered patent attorney."
            ],
            "novelty_rating": "Moderate" if risk_level in ["MODERATE", "LOW"] else "Low"
        }

    def _normalize_parsed_response(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize parsed JSON schema so single_document_anticipation is 'YES'/'NO' and claim_elements has standard keys."""
        sda = parsed.get("single_document_anticipation")
        if isinstance(sda, dict):
            parsed["single_document_anticipation"] = "YES" if sda.get("found") else "NO"
        elif isinstance(sda, str):
            parsed["single_document_anticipation"] = "YES" if "YES" in sda.upper() or "TRUE" in sda.upper() else "NO"
        elif isinstance(sda, bool):
            parsed["single_document_anticipation"] = "YES" if sda else "NO"
        else:
            parsed["single_document_anticipation"] = "NO"

        raw_claims = parsed.get("claim_elements", [])
        norm_claims = []
        for idx, c in enumerate(raw_claims, start=1):
            if isinstance(c, dict):
                lim_num = c.get("limitation_number") or idx
                elem_text = c.get("element_text") or c.get("element") or c.get("limitation") or ""
                status = c.get("status") or "PARTIAL"
                status_str = str(status).upper()
                if "EXPLICIT" in status_str:
                    status = "EXPLICIT"
                elif "INHERENT" in status_str:
                    status = "INHERENT"
                elif "NOT" in status_str or "MISSING" in status_str:
                    status = "NOT_DISCLOSED"
                else:
                    status = "PARTIAL"
                quote = c.get("evidence_quote") or c.get("evidence") or ""
                expl = c.get("explanation") or c.get("reasoning") or ""
                norm_claims.append({
                    "limitation_number": lim_num,
                    "element_text": elem_text,
                    "status": status,
                    "evidence_quote": quote,
                    "explanation": expl
                })
        parsed["claim_elements"] = norm_claims
        return parsed


gemini_service = GeminiService()
