import logging
import json
from typing import Dict, Any, List, Optional
from app.core.config import settings
logger = logging.getLogger("patentlens.groq")

class GroqService:
    """Service for generating evidence-based patent claim examination using Groq (llama-3.3-70b-versatile)."""

    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.model_name = settings.GROQ_MODEL or "llama-3.3-70b-versatile"

        self.client = None
        self._initialize_client()

    def _initialize_client(self):
        api_key = settings.GROQ_API_KEY
        if api_key and len(api_key.strip()) > 10 and not api_key.startswith("your_"):
            try:
                from groq import Groq
                self.client = Groq(api_key=api_key.strip())
                logger.info(f"Groq client initialized for model '{self.model_name}'.")
            except Exception as e:
                logger.warning(f"Could not load groq client: {e}")
                self.client = None
        else:
            logger.info("Groq API key not configured. Heuristic NLP analysis will be used.")

    @property
    def is_configured(self) -> bool:
        return bool(self.client is not None or (self.api_key and len(self.api_key.strip()) > 10 and not self.api_key.startswith("your_")))

    def analyze_invention(
        self,
        title: str,
        problem_statement: str,
        description: str,
        # pyrefly: ignore [unknown-name]
        keywords: Optional[List[str]] = None,
        domain: str = ""
    ) -> Dict[str, Any]:
        """Analyze user invention using Groq LLaMA 3.3 70B to extract structured features & search queries."""
        title = title or ""
        problem_statement = problem_statement or ""
        description = description or ""
        keywords = keywords or []
        domain = domain or "Technology"

        import os
        is_testing = (getattr(settings, "TESTING", False) or os.getenv("TESTING", "").lower() == "true") and not (getattr(settings, "LIVE_BENCHMARK", False) or os.getenv("LIVE_BENCHMARK", "").lower() == "true")
        is_mocked = "mock" in type(self.client).__module__.lower() or "mock" in type(self.client).__name__.lower() if self.client else False
        if is_testing and not is_mocked:
            try:
                from app.services.gemini_service import gemini_service
            except ImportError:
                from app.services.gemini_service import gemini_service
            return gemini_service._heuristic_invention_analysis(title, problem_statement, description, keywords, domain)

        client = self.client
        if self.is_configured and client is not None:
            try:
                system_prompt = "You are a Senior Patent Examiner and IP Analyst. Return strict valid JSON only."
                user_prompt = f"""
Analyze the target invention disclosure and decompose it into structured technical concepts for prior-art retrieval.

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
  "essential_features": ["essential claim feature 1", "essential claim feature 2"],
  "optional_features": ["optional feature 1"],
  "technical_features": ["component + function + relationship 1", "component + function + relationship 2"],
  "structured_quadruplets": [
    {{
      "component": "controller",
      "function": "adjusts threshold",
      "relationship": "coupled to sensor",
      "purpose": "prevents false positive"
    }}
  ],
  "distinctive_features": ["distinctive concept 1", "distinctive concept 2"],
  "search_queries": [
    "\"{title}\" AND \"{domain}\"",
    "query strategy 2",
    "query strategy 3",
    "query strategy 4",
    "query strategy 5",
    "query strategy 6",
    "query strategy 7",
    "query strategy 8"
  ],
  "possible_cpc_ipc_classes": ["CPC_CODE_1"]
}}
"""
                import concurrent.futures
                def _call_groq_inv():
                    return client.chat.completions.create(
                        model=self.model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.1
                    )
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(_call_groq_inv)
                    res = fut.result(timeout=12.0)
                text_content = res.choices[0].message.content or "{}"
                parsed = json.loads(text_content)
                try:
                    from app.services.gemini_service import gemini_service
                except ImportError:
                    from app.services.gemini_service import gemini_service
                return gemini_service._clean_invention_analysis(parsed, title, keywords, domain)
            except Exception as e:
                logger.warning(f"Groq analyze_invention error/timeout ({e}). Falling back to Gemini / Heuristic.")

        try:
            from app.services.gemini_service import gemini_service
        except ImportError:
            from app.services.gemini_service import gemini_service
        return gemini_service.analyze_invention(title, problem_statement, description, keywords, domain)

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
        feature-by-feature prior-art comparison using Groq LLaMA 3.3.
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
            return self._generate_heuristic_pair_analysis(
                target_title, target_description, patent_number, patent_title, patent_abstract, similarity_score, patent_description
            )

        client = self.client
        if self.is_configured and client is not None:
            try:
                system_prompt = "You are a Senior Patent Examiner conducting strict prior-art claim analysis. Output strict valid JSON only."
                user_prompt = f"""
You are a Senior Patent Examiner conducting a rigorous prior-art anticipation and feature disclosure comparison.

EXAMINATION RULES:
1. Break the target invention claim/description into atomic technical limitations/elements.
2. Compare EVERY limitation against the supplied prior-art document ({patent_number}: '{patent_title}').
3. Classify EVERY limitation as exactly ONE of:
   - EXPLICIT: Explicitly disclosed in prior-art text.
   - INHERENT: Inherent technical feature necessarily present in the disclosed prior-art structure.
   - PARTIAL: Partially disclosed or broadly suggested, missing structural details.
   - NOT_DISCLOSED: Completely absent from the prior-art document.
4. Provide explicit supporting quotes/evidence directly from the prior-art text for every classification. If evidence is insufficient, set evidence to "INSUFFICIENT_EVIDENCE".
5. Identify all missing technical features in "missing_elements".
6. Determine whether THIS SINGLE PRIOR-ART DOCUMENT discloses ALL essential limitations ("single_document_anticipation": {{"found": true/false, "reason": "string"}}).
7. NEVER combine multiple documents when determining single-document anticipation.
8. Similar terminology MUST NOT automatically be treated as identical unless structural identity is shown in prior-art text.
9. Calculate "technical_feature_coverage" as the percentage (0-100%) of target claim limitations classified as EXPLICIT, INHERENT, or PARTIAL.
10. Calculate "confidence" as an integer (0-100) representing your confidence in the evidence analysis.
11. Do NOT invent claims, dates, inventors, or prior-art disclosure. Do not make final legal conclusions of patentability.

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
  "claim_elements": [
    {{
      "element": "Atomic technical limitation name",
      "status": "EXPLICIT | INHERENT | PARTIAL | NOT_DISCLOSED",
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
  "reasoning": "Comprehensive examination explanation.",
  "relevance_explanation": "2-sentence relevance summary.",
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
      "match_level": "strong",
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
      "explanation": "Both systems disclose sensor routines for detecting obstacles.",
      "evidence_quote": "Auxiliary sensor bridge continuously monitors resonant frequency shifts and metallic debris on charging pad surface.",
      "confidence": 92.0
    }}
  ]
}}
"""

                import concurrent.futures
                def _call_groq_pair():
                    return client.chat.completions.create(
                        model=self.model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.1
                    )
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(_call_groq_pair)
                    response = fut.result(timeout=12.0)
                text_content = response.choices[0].message.content or "{}"
                parsed = json.loads(text_content)
                parsed["ai_powered"] = True
                parsed["model_used"] = self.model_name
                parsed["provider"] = "groq"
                return self._normalize_parsed_response(parsed)

            except Exception as e:
                logger.error(f"Error in Groq patent pair analysis: {e}")

        # Fallback to Gemini Service or Heuristic NLP
        try:
            from app.services.gemini_service import gemini_service
            return gemini_service.analyze_patent_pair(
                target_title, target_problem, target_description,
                patent_number, patent_title, patent_abstract, patent_description,
                similarity_score
            )
        except Exception:
            return self._generate_heuristic_pair_analysis(
                target_title, target_description, patent_number, patent_title, patent_abstract, similarity_score
            )

    def _generate_heuristic_pair_analysis(self, *args, **kwargs):
        try:
            from app.services.gemini_service import gemini_service
        except ImportError:
            from app.services.gemini_service import gemini_service
        return gemini_service._generate_heuristic_pair_analysis(*args, **kwargs)

    def generate_novelty_analysis(
        self,
        invention_title: str,
        problem_statement: str,
        description: str,
        matched_patents: List[Dict[str, Any]],
        risk_level: str
    ) -> Dict[str, Any]:
        """Generate high-level overall summary across top prior-art matches using Groq LLaMA 3.3."""
        client = self.client
        if self.is_configured and client is not None:
            try:
                patents_summary = "\n".join([
                    f"- Patent {p.get('patent_number', 'N/A')}: {p.get('title', '')} (SBERT Sim: {p.get('final_score', 0)}%)\n"
                    f"  Abstract: {p.get('abstract', '')[:200]}..."
                    for p in matched_patents[:3]
                ])

                user_prompt = f"""
You are a Senior AI Patent Examiner. Provide a high-level preliminary prior-art assessment for the target invention using Groq LLaMA 3.3.
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
                import concurrent.futures
                def _call_groq_nov():
                    return client.chat.completions.create(
                        model=self.model_name,
                        messages=[{"role": "user", "content": user_prompt}],
                        response_format={"type": "json_object"},
                        temperature=0.2
                    )
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(_call_groq_nov)
                    response = fut.result(timeout=12.0)
                text_content = response.choices[0].message.content or "{}"
                parsed = json.loads(text_content)
                parsed["ai_powered"] = True
                parsed["model_used"] = self.model_name
                parsed["provider"] = "groq"
                return parsed

            except Exception as e:
                logger.error(f"Error in Groq novelty analysis: {e}")

        try:
            from app.services.gemini_service import gemini_service
        except ImportError:
            from app.services.gemini_service import gemini_service
        return gemini_service.generate_novelty_analysis(invention_title, problem_statement, description, matched_patents, risk_level)

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

        # Normalize target response structure fields & feature comparisons
        raw_matched = parsed.get("matched_features", [])
        norm_matched = []
        evidence_list = []
        partial_list = []

        for m in raw_matched:
            if isinstance(m, dict):
                feat_name = m.get("feature") or m.get("target_feature") or ""
                ev_quote = m.get("evidence") or m.get("evidence_quote") or m.get("patent_evidence") or "NOT_FOUND"
                m_level = str(m.get("match_level") or m.get("match_type") or "STRONG_MATCH").upper()
                if "STRONG" in m_level:
                    m_level = "STRONG_MATCH"
                elif "PARTIAL" in m_level:
                    m_level = "PARTIAL_MATCH"
                elif "WEAK" in m_level:
                    m_level = "WEAK_MATCH"
                else:
                    m_level = "NOT_FOUND"

                section = m.get("source_section") or "specification"
                conf = float(m.get("confidence") or 85.0)

                norm_matched.append({
                    "feature": feat_name,
                    "target_feature": feat_name,
                    "match_type": m_level,
                    "match_level": m_level.lower().replace("_match", ""),
                    "evidence": ev_quote,
                    "patent_evidence": ev_quote,
                    "source_section": section,
                    "confidence": conf
                })
                if ev_quote and ev_quote != "NOT_FOUND":
                    evidence_list.append(f"Feature '{feat_name}': \"{ev_quote}\"")
                if "PARTIAL" in m_level:
                    partial_list.append(feat_name)
            elif isinstance(m, str):
                norm_matched.append({
                    "feature": m,
                    "target_feature": m,
                    "match_type": "STRONG_MATCH",
                    "match_level": "strong",
                    "evidence": "NOT_FOUND",
                    "patent_evidence": "NOT_FOUND",
                    "source_section": "specification",
                    "confidence": 70.0
                })

        parsed["matched_features"] = norm_matched
        parsed["partial_matches"] = partial_list or parsed.get("partial_matches", [])
        parsed["unmatched_features"] = parsed.get("unmatched_features") or parsed.get("missing_elements") or []
        parsed["evidence"] = evidence_list or ["NOT_FOUND"]
        parsed["technical_summary"] = parsed.get("technical_summary") or parsed.get("relevance_explanation") or "Technical disclosure compared against invention."
        parsed["relevance_explanation"] = parsed.get("relevance_explanation") or parsed.get("technical_summary") or "Technical disclosure compared against invention."

        return parsed


groq_service = GroqService()
