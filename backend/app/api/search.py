import json
from app.schemas.schemas import ComponentBreakdownItem
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, IS_POSTGRES
from app.core.security import get_current_user
from app.models.models import User, Patent, Search, SearchResult
from app.schemas.schemas import (
    PriorArtSearchRequest, PriorArtSearchResponse, SearchResultItem,
    SearchSummary, SearchHistoryItem, PatentOut
)
from ml.preprocessing import validate_invention_input, prepare_combined_text
from ml.keyword_extractor import extract_technical_concepts
from ml.embedding_service import embedding_service
from ml.similarity_engine import compute_hybrid_score, calculate_cosine_similarity
from ml.risk_classifier import classify_prior_art_risk, get_similarity_level_label
from app.services.llm_factory import get_llm_service
from app.services.patent_api_service import patent_api_service
from app.services.lens_api_service import lens_api_service
router = APIRouter(prefix="/search", tags=["Prior-Art Search"])

@router.post("", response_model=PriorArtSearchResponse, status_code=status.HTTP_201_CREATED)
def perform_prior_art_search(
    request: PriorArtSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Perform AI-assisted preliminary prior-art search:
    1. Preprocess input text
    2. Extract technical concepts
    3. Generate SBERT 384-d embedding
    4. Perform vector similarity search against patent database
    5. Compute hybrid similarity score (Semantic 70%, Keyword 20%, Domain 10%)
    6. Classify risk level (LOW, MODERATE, HIGH, VERY HIGH)
    7. Persist search and search results in database
    """
    import logging
    logger = logging.getLogger("patentlens.search")

    val_res = validate_invention_input(request.title, request.description)
    if not val_res["valid"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=val_res["error"])

    target_full_text = f"{request.title} {request.problem_statement} {request.description}"
    user_concepts = extract_technical_concepts(target_full_text)
    
    # 1. Use LLM service (Groq / Gemini) to understand invention, extract features & search queries
    llm_service = get_llm_service()
    import concurrent.futures

    try:
        def _do_inv_analysis():
            return llm_service.analyze_invention(
                title=request.title,
                problem_statement=request.problem_statement,
                description=request.description,
                keywords=request.keywords,
                domain=request.domain
            )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as inv_pool:
            inv_fut = inv_pool.submit(_do_inv_analysis)
            invention_analysis = inv_fut.result(timeout=12.0)
    except Exception as e_inv:
        logger.warning(f"[SEARCH ROUTE] Invention analysis timeout/note ({e_inv}). Falling back to instant heuristic NLP analysis.")
        try:
            from app.services.gemini_service import gemini_service
        except ImportError:
            from app.services.gemini_service import gemini_service
        invention_analysis = gemini_service._heuristic_invention_analysis(
            request.title, request.problem_statement, request.description, request.keywords, request.domain
        )

    gemini_features = invention_analysis.get("technical_features", [])
    gemini_essential = invention_analysis.get("essential_features", [])
    gemini_optional = invention_analysis.get("optional_features", [])
    gemini_quads = invention_analysis.get("structured_quadruplets", [])
    gemini_queries = invention_analysis.get("search_queries", [])
    cpc_candidates = invention_analysis.get("cpc_candidates", [])

    logger.info("[DEBUG PIPELINE] ==================== INVENTIVE STEP 1: GEMINI ====================")
    logger.info(f"[DEBUG PIPELINE] Target Invention: '{request.title}' | Domain: '{request.domain}'")
    logger.info(f"[DEBUG PIPELINE] Technical Problem: {invention_analysis.get('technical_problem', '')}")
    logger.info(f"[DEBUG PIPELINE] Essential Features: {gemini_essential}")
    logger.info(f"[DEBUG PIPELINE] Gemini Search Queries (8 Strategies): {gemini_queries}")
    logger.info(f"[DEBUG PIPELINE] Gemini CPC Candidates: {cpc_candidates}")

    combined_text = prepare_combined_text(
        title=request.title,
        problem_statement=request.problem_statement,
        description=request.description,
        keywords=request.keywords
    )
    user_embedding = embedding_service.generate_embedding(combined_text)

    # 2. Fetch live patent candidates via The Lens Patent API with configurable pipeline timeout
    import concurrent.futures
    try:
        def _do_external_fetch():
            return patent_api_service.fetch_and_cache_external_patents(
                db=db,
                title=request.title,
                keywords=request.keywords,
                domain=request.domain,
                search_queries=gemini_queries,
                cpc_candidates=cpc_candidates,
                limit=50
            )
        pipeline_timeout = getattr(settings, "EXTERNAL_API_PIPELINE_TIMEOUT", 25.0)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ext_pool:
            ext_fut = ext_pool.submit(_do_external_fetch)
            api_stats = ext_fut.result(timeout=pipeline_timeout)
        logger.info(f"[DEBUG PIPELINE] Step 2 Lens/arXiv Search Stats: {api_stats}")
    except Exception as e:
        logger.warning(f"[PATENT API] External search timeout/note ({e}). Proceeding immediately with local dataset candidates.")
        fallback_lens_status = "LENS_API_UNAVAILABLE" if lens_api_service.is_configured else "LENS_UNCONFIGURED"
        api_stats = {"patents_retrieved": 0, "patents_searched": 0, "lens_api_status": fallback_lens_status}


    try:
        from app.core.database import IS_POSTGRES, HAS_PGVECTOR
    except ImportError:
        from app.core.database import IS_POSTGRES, HAS_PGVECTOR
    import numpy as np

    live_patents = []
    recent_patents = []
    seed_patents = []
    try:
        live_patents = db.query(Patent).filter(Patent.source_status == "LIVE_API").order_by(Patent.id.desc()).limit(150).all()
        recent_patents = db.query(Patent).order_by(Patent.id.desc()).limit(150).all()
        seed_patents = db.query(Patent).limit(100).all()
    except Exception:
        pass

    mongo_patents = []
    try:
        from app.models.models import PatentDoc
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            mongo_patents = loop.run_until_complete(PatentDoc.find().limit(300).to_list())
        except Exception:
            mongo_patents = asyncio.run(PatentDoc.find().limit(300).to_list())
    except Exception as e_mfetch:
        logger.warning(f"MongoDB patent fetch note: {e_mfetch}")

    patent_map = {}
    for p in (live_patents + recent_patents + seed_patents):
        if p and p.patent_number:
            patent_map[p.patent_number] = p

    for mp in mongo_patents:
        if mp and mp.patent_number and mp.patent_number not in patent_map:
            patent_map[mp.patent_number] = mp

    all_patents = list(patent_map.values())


    if not all_patents:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Patent database is empty. Please run seed script first."
        )

    # Ultra-fast NumPy vector cosine pre-filtering
    candidate_patents = all_patents
    if len(all_patents) > 100 and user_embedding:
        try:
            valid_patents = []
            emb_vectors = []
            u_arr = np.array(user_embedding, dtype=np.float32)
            u_norm = np.linalg.norm(u_arr)

            for p in all_patents:
                p_emb = p.embedding
                if isinstance(p_emb, str):
                    try:
                        p_emb = json.loads(p_emb)
                    except Exception:
                        p_emb = None
                if p_emb and len(p_emb) == 384:
                    valid_patents.append(p)
                    emb_vectors.append(p_emb)

            if emb_vectors and u_norm > 0:
                mat = np.array(emb_vectors, dtype=np.float32)
                norms = np.linalg.norm(mat, axis=1)
                norms[norms == 0] = 1e-9
                sims = np.dot(mat, u_arr) / (norms * u_norm)
                
                # Pair patents with similarities and pick top 100
                sorted_patents = [p for p, s in sorted(zip(valid_patents, sims), key=lambda x: x[1], reverse=True)]
                candidate_patents = sorted_patents[:100]
        except Exception as e_pref:
            logger.warning(f"Vector pre-filtering fallback: {e_pref}")
            candidate_patents = all_patents[:100]

    try:
        from ml.similarity_engine import is_technical_mismatch
    except ImportError:
        from ml.similarity_engine import is_technical_mismatch

    scored_items = []
    for patent in candidate_patents:
        # Stage 3 Funnel Gate: Technical Mismatch Filter (Kill false positives)
        if is_technical_mismatch(
            user_domain=request.domain,
            user_text=target_full_text,
            patent_title=patent.title,
            patent_abstract=patent.abstract,
            patent_domain=patent.domain
        ):
            logger.info(f"[STAGE 3 FUNNEL] Disqualified technical mismatch candidate: '{patent.title}'")
            continue

        patent_dict = {
            "title": patent.title,
            "abstract": patent.abstract,
            "description": patent.description,
            "claims": patent.claims,
            "domain": patent.domain,
            "cpc_codes": patent.cpc_codes,
            "cpc_candidates": cpc_candidates
        }
        
        patent_emb = patent.embedding
        if isinstance(patent_emb, str):
            patent_emb = json.loads(patent_emb)

        scores = compute_hybrid_score(
            user_embedding=user_embedding,
            patent_embedding=patent_emb,
            user_keywords=request.keywords,
            user_concepts=user_concepts,
            user_domain=request.domain,
            patent=patent_dict,
            target_text_for_concepts=target_full_text,
            distinctive_features=invention_analysis.get("distinctive_features"),
            technical_features=gemini_features,
            essential_features=gemini_essential
        )

        scored_items.append({
            "patent": patent,
            "scores": scores
        })

    # Robust generalized patent family deduplication & metric tracking
    import re
    def _normalize_title_stem(title_str: str) -> str:
        if not title_str:
            return ""
        t = re.sub(r'\s*-\s*Variant\s*\d+', '', title_str, flags=re.IGNORECASE)
        t = re.sub(r'\s*-\s*Part\s*\d+', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\s*\((Continuation|Divisional|Reissue|Variant)\s*\d*\)', '', t, flags=re.IGNORECASE)
        t = re.sub(r'[^a-zA-Z0-9\s]', ' ', t).lower()
        words = [w for w in t.split() if len(w) > 3]
        return " ".join(words[:6])

    def _get_fam_key(pat_obj: Any) -> str:
        fam_id = getattr(pat_obj, "simple_family_id", None) or getattr(pat_obj, "family_id", None)
        if fam_id and str(fam_id).strip() and str(fam_id).strip() != "None":
            return f"FAM_{str(fam_id).strip().upper()}"
        
        t_stem = _normalize_title_stem(getattr(pat_obj, "title", ""))
        if t_stem and len(t_stem) > 10:
            return f"TITLE_{t_stem}"
            
        p_num = (pat_obj.patent_number or "").strip().upper()
        clean = p_num.split("-")[-1] if "-" in p_num else p_num
        clean = re.sub(r'[A-Z]\d?$', '', clean)
        return clean if clean else p_num

    candidates_with_family_ids_cnt = sum(
        1 for item in scored_items
        if (getattr(item["patent"], "simple_family_id", None) or getattr(item["patent"], "family_id", None))
    )

    family_grouped: Dict[str, Any] = {}
    for item in scored_items:
        fam_key = _get_fam_key(item["patent"])

        if fam_key not in family_grouped:
            family_grouped[fam_key] = item
        else:
            prev = family_grouped[fam_key]
            prev_claims_len = len(prev["patent"].claims or "")
            curr_claims_len = len(item["patent"].claims or "")
            if item["scores"]["final_score"] > prev["scores"]["final_score"] or (item["scores"]["final_score"] == prev["scores"]["final_score"] and curr_claims_len > prev_claims_len):
                family_grouped[fam_key] = item

    # Stage 4 Technical Relevance Gate (Non-forced Top N): Reject candidates with score < 30% and 0 feature matches
    deduped_scored_items = list(family_grouped.values())
    deduped_scored_items.sort(key=lambda x: x["scores"]["final_score"], reverse=True)

    gated_candidates = []
    rejected_count = 0
    for item in deduped_scored_items:
        sc = item["scores"]
        has_matched_feat = sc.get("matched_feature_count", 0) > 0 or len(sc.get("strong_matches", [])) > 0 or len(sc.get("partial_matches", [])) > 0
        has_dist_match = sc.get("distinctive_score", 0.0) > 0.0
        
        # Only retain candidates passing technical relevance gate (Score >= 30% or matching features)
        if sc["final_score"] < 30.0 and not has_matched_feat and not has_dist_match:
            rejected_count += 1
            logger.info(f"[STAGE 4 REJECTION] Rejected candidate '{item['patent'].title}' (Score: {sc['final_score']}%) Reason: IRRELEVANT_NO_TECHNICAL_OVERLAP")
        else:
            gated_candidates.append(item)

    top_candidates = [item for item in gated_candidates if item["scores"]["final_score"] >= 30.0 or item["scores"]["matched_feature_count"] > 0]
    top_10 = top_candidates[:10]
    if not top_10 and deduped_scored_items:
        logger.info("[SEARCH ROUTE] All candidates scored below 30.0% threshold. Returning top deduplicated candidates categorized as TECHNICALLY_DISTINCT.")
        top_10 = deduped_scored_items[:10]

    # Iterative Search & Citation Expansion for top candidates
    iterative_retrieved = 0
    citation_retrieved = 0
    top_pat_nums = [item["patent"].patent_number for item in top_10]
    if top_pat_nums:
        try:
            def _do_citation():
                return patent_api_service.execute_citation_expansion(db=db, top_patent_numbers=top_pat_nums)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as cit_pool:
                cit_fut = cit_pool.submit(_do_citation)
                citation_recs = cit_fut.result(timeout=1.5)
                citation_retrieved = len(citation_recs)
        except Exception as e:
            logger.warning(f"Citation expansion note/timeout: {e}")

    highest_similarity = top_10[0]["scores"]["final_score"] if top_10 else 0.0
    highest_semantic_similarity = max((item["scores"]["semantic_score"] for item in top_10), default=0.0)
    risk_info = classify_prior_art_risk(highest_similarity)

    vhigh_count = 0
    high_count = 0
    mod_count = 0
    low_count = 0

    for item in top_10:
        f_score = item["scores"]["final_score"]
        r_level = classify_prior_art_risk(f_score)["risk_level"]
        if r_level == "VERY HIGH":
            vhigh_count += 1
        elif r_level == "HIGH":
            high_count += 1
        elif r_level == "MODERATE":
            mod_count += 1
        else:
            low_count += 1

    total_matches_count = len(top_10)

    pat_searched: int = int(api_stats.get("patents_searched") or len(candidate_patents))
    pat_retrieved: int = int(api_stats.get("patents_retrieved") or 0)
    pat_shortlisted = len(top_10)
    pat_deeply_analyzed = len(top_10)

    lens_status: str = str(api_stats.get("lens_api_status") or "LENS_OK")

    # Structured Stage-by-Stage Retrieval Quality Logging & Single Search Trace
    logger.info("==================================================")
    logger.info(f"[END-TO-END SEARCH TRACE] User Invention: '{request.title}' | Domain: '{request.domain}'")
    logger.info(f"[END-TO-END SEARCH TRACE] Extracted Essential Features: {gemini_essential}")
    logger.info(f"[END-TO-END SEARCH TRACE] Generated Queries: {gemini_queries}")
    logger.info(f"[END-TO-END SEARCH TRACE] Lens API Endpoint: https://api.lens.org/patent/search | Method: POST")
    logger.info(f"[END-TO-END SEARCH TRACE] Lens API Status: {lens_status} | Live Records Returned: {pat_retrieved}")
    logger.info(f"[END-TO-END SEARCH TRACE] DB Candidates Evaluated: {len(candidate_patents)} | Deduplicated Families: {len(family_grouped)}")
    logger.info(f"[END-TO-END SEARCH TRACE] Stage 4 Rejected Irrelevant Candidates: {rejected_count}")
    logger.info(f"[END-TO-END SEARCH TRACE] Final Shortlisted Technically Relevant Candidates: {len(top_10)}")
    logger.info(f"[END-TO-END SEARCH TRACE] Highest Similarity Score: {highest_similarity}% | Risk: {risk_info['risk_level']}")
    logger.info("==================================================")

    patents_with_claims = sum(
        1 for item in scored_items
        if (item["patent"].claims and len(item["patent"].claims.strip()) > 10)
        or (item["patent"].abstract and len(item["patent"].abstract.strip()) > 20)
        or (item["patent"].description and len(item["patent"].description.strip()) > 30)
    )
    patents_with_full_text = sum(
        1 for item in scored_items
        if (item["patent"].description and len(item["patent"].description.strip()) > 30)
        or (item["patent"].abstract and len(item["patent"].abstract.strip()) > 30)
    )
    evidence_verified = sum(
        1 for item in top_10
        if any(e.get("verified") for e in item["scores"].get("evidence_items", []))
    )

    try:
        from app.schemas.schemas import ScoreBreakdown, PipelineMetrics, PatentFamilyMember
    except ImportError:
        from app.schemas.schemas import ScoreBreakdown, PipelineMetrics, PatentFamilyMember

    pat_searched_val = pat_searched
    pat_retrieved_val = pat_retrieved

    pipeline_metrics = PipelineMetrics(
        patents_searched=pat_searched_val,
        patents_retrieved=pat_retrieved_val,
        lens_records_retrieved=pat_retrieved_val,
        database_fallback_candidates=len(candidate_patents) if pat_retrieved_val == 0 else 0,
        final_shortlisted=len(top_10),
        total_candidates_evaluated=len(candidate_patents) + pat_retrieved_val,
        raw_candidates=len(candidate_patents),
        candidates_with_family_ids=candidates_with_family_ids_cnt,
        post_dedup_candidates=len(deduped_scored_items),
        vector_shortlisted=pat_shortlisted,
        unique_families=len(family_grouped),
        semantic_candidates=len(candidate_patents),
        technical_candidates=len(top_10),
        patents_with_claims=patents_with_claims,
        patents_with_full_text=patents_with_full_text,
        evidence_verified_matches=evidence_verified,
        iterative_wave_retrieved=iterative_retrieved,
        citation_expansions_found=citation_retrieved,
        lens_api_status=lens_status
    )

    search_record = Search(
        user_id=current_user.id,
        invention_title=request.title,
        domain=request.domain,
        problem_statement=request.problem_statement,
        description=request.description,
        keywords=request.keywords,
        risk_level=risk_info["risk_level"],
        highest_similarity=highest_similarity,
        total_results=total_matches_count,
        very_high_similarity=vhigh_count,
        high_similarity=high_count,
        moderate_similarity=mod_count,
        low_similarity=low_count,
        patents_searched=pat_searched,
        patents_retrieved=pat_retrieved,
        patents_shortlisted=pat_shortlisted,
        patents_deeply_analyzed=pat_deeply_analyzed,
        pipeline_metrics=pipeline_metrics.model_dump(mode="json")
    )
    try:
        db.add(search_record)
        db.commit()
        db.refresh(search_record)
    except Exception as e_sql_s:
        logger.warning(f"SQL search record save note: {e_sql_s}")


    llm_service = get_llm_service()
    result_items_response = []

    # Parallelize patent pair feature analysis across top candidates
    from concurrent.futures import ThreadPoolExecutor

    def _execute_pair_analysis(indexed_tuple):
        i_idx, item_obj = indexed_tuple
        p_obj = item_obj["patent"]
        s_obj = item_obj["scores"]
        try:
            res_analysis = llm_service.analyze_patent_pair(
                target_title=request.title,
                target_problem=request.problem_statement,
                target_description=request.description,
                patent_number=p_obj.patent_number,
                patent_title=p_obj.title,
                patent_abstract=p_obj.abstract,
                patent_description=p_obj.description,
                similarity_score=s_obj["final_score"]
            )
        except Exception as e_pair:
            logger.warning(f"Pair analysis thread fallback for {p_obj.patent_number}: {e_pair}")
            res_analysis = llm_service._normalize_parsed_response(
                llm_service._generate_heuristic_pair_analysis(
                    target_title=request.title,
                    target_description=request.description,
                    patent_number=p_obj.patent_number,
                    patent_title=p_obj.title,
                    patent_abstract=p_obj.abstract,
                    similarity_score=s_obj["final_score"],
                    patent_description=p_obj.description
                )
            )
        return i_idx, res_analysis

    pair_analysis_map = {}
    if top_10:
        pair_timeout = 1.0 if (not llm_service.is_configured or lens_status == "LENS_RATE_LIMITED") else 4.0
        with ThreadPoolExecutor(max_workers=min(10, len(top_10))) as pool:
            futures = [pool.submit(_execute_pair_analysis, item_tuple) for item_tuple in enumerate(top_10, start=1)]
            for fut in futures:
                try:
                    i_idx, res_analysis = fut.result(timeout=pair_timeout)
                    pair_analysis_map[i_idx] = res_analysis
                except Exception as e_fut:
                    logger.warning(f"Thread pool task timeout/error: {e_fut}")

    raw_live_nums = api_stats.get("live_patent_numbers") if isinstance(api_stats, dict) else None
    live_retrieved_set = set(raw_live_nums) if isinstance(raw_live_nums, (list, tuple, set)) else set()

    for idx, item in enumerate(top_10, start=1):
        pat = item["patent"]
        sc = item["scores"]
        res_status = "TECHNICALLY_RELEVANT"

        f_score = sc["final_score"]

        # Retrieve grounded patent pair feature comparison and limitation analysis
        raw_pair = pair_analysis_map.get(idx) or llm_service._generate_heuristic_pair_analysis(
            target_title=request.title,
            target_description=request.description,
            patent_number=pat.patent_number,
            patent_title=pat.title,
            patent_abstract=pat.abstract,
            similarity_score=f_score,
            patent_description=pat.description
        )
        pair_analysis = llm_service._normalize_parsed_response(raw_pair)

        sb_dict = sc.get("score_breakdown", {})
        conf_score = sc.get("confidence_score") if sc.get("confidence_score") is not None else 45.0

        def _get_comp_item(key, fallback_val, fallback_weight, fallback_status="AVAILABLE"):
            c_data = sb_dict.get(key, {})
            if isinstance(c_data, dict):
                return ComponentBreakdownItem(
                    value=c_data.get("value"),
                    weight=c_data.get("weight", fallback_weight),
                    effective_weight=c_data.get("effective_weight", fallback_weight),
                    contribution=c_data.get("contribution", 0.0),
                    status=c_data.get("status", fallback_status)
                )
            return ComponentBreakdownItem(
                value=fallback_val,
                weight=fallback_weight,
                effective_weight=fallback_weight,
                contribution=round((fallback_val or 0.0) * fallback_weight, 1),
                status=fallback_status
            )

        score_bd_obj = ScoreBreakdown(
            semantic=_get_comp_item("semantic", sc["semantic_score"], 0.25),
            technical_features=_get_comp_item("technical_features", sc["keyword_score"], 0.35, "AVAILABLE" if sc.get("has_target_features", True) else "UNAVAILABLE"),
            evidence=_get_comp_item("evidence", sc.get("evidence_score", 0.0), 0.20, "AVAILABLE" if sc.get("claims_status") == "AVAILABLE" or sc.get("full_text_status") == "AVAILABLE" else "UNAVAILABLE"),
            concepts=_get_comp_item("concepts", sc.get("distinctive_score", 0.0), 0.10),
            domain_cpc=_get_comp_item("domain_cpc", sc["domain_score"], 0.10),
            semantic_similarity=sb_dict.get("semantic_similarity", sc["semantic_score"]),
            technical_features_score=sb_dict.get("technical_features_score", sc["keyword_score"]),
            evidence_strength=sb_dict.get("evidence_strength", sc.get("evidence_score", 0.0)),
            distinctive_concepts=sb_dict.get("distinctive_concepts", sc.get("distinctive_score", 0.0)),
            domain_cpc_alignment=sb_dict.get("domain_cpc_alignment", sc["domain_score"]),
            technology_domain_score=sb_dict.get("technology_domain_score", sc["domain_score"]),
            cpc_match_score=sb_dict.get("cpc_match_score", 0.0),
            final_score=sc["final_score"],
            confidence_score=conf_score,
            calculation_method=sb_dict.get("calculation_method", "STANDARD_FULL_WEIGHTS"),
            is_gated=sb_dict.get("is_gated", False),
            score_cap=sb_dict.get("score_cap"),
            score_cap_reason=sb_dict.get("score_cap_reason"),
            formula_explanation=sb_dict.get("formula_explanation", "Final Score = (25% Semantic) + (35% Technical Features) + (20% Evidence) + (10% Distinctive Concepts) + (10% Domain/CPC)")
        )

        # Calculate Temporal Status according to Phase 16
        p_date = str(pat.publication_date or "").strip()[:10]
        prio_date = str(getattr(pat, "earliest_priority_date", "") or p_date).strip()[:10]
        r_date = request.reference_date.strip()[:10] if request.reference_date else ""

        if not r_date:
            temporal_status = "DATE_UNAVAILABLE"
            temporal_conclusion = f"Reference date not specified by user. Document publication date is {p_date}."
        elif p_date and p_date == r_date:
            temporal_status = "SAME_DATE"
            temporal_conclusion = f"Published on {p_date}, which is the SAME date as reference date ({r_date})."
        elif prio_date and p_date and prio_date < r_date and p_date > r_date:
            temporal_status = "EARLIER_PRIORITY_BUT_PUBLISHED_AFTER"
            temporal_conclusion = f"Earlier Priority ({prio_date}) — Published After Reference Date ({p_date} > {r_date})."
        elif p_date and p_date > r_date:
            temporal_status = "PUBLISHED_AFTER_REFERENCE"
            temporal_conclusion = f"Published on {p_date}, which is AFTER reference date ({r_date})."
        elif p_date and p_date < r_date:
            temporal_status = "PUBLISHED_BEFORE_REFERENCE"
            temporal_conclusion = f"Published on {p_date}, which is BEFORE reference date ({r_date})."
        else:
            temporal_status = "TEMPORAL_STATUS_UNCERTAIN"
            temporal_conclusion = f"Publication timeline uncertain (Pub Date: {p_date})."

        ev_status = sc.get("evidence_status", "VERIFIED")
        rel_info = classify_prior_art_risk(f_score)
        relevance_level = rel_info["label"]

        if f_score < 30.0:
            res_status = "TECHNICALLY_DISTINCT"
            overall_res = "NON_ANTICIPATED"
        elif f_score < 50.0:
            res_status = "PARTIALLY_RELEVANT"
            overall_res = "PARTIALLY_DISCLOSED"
        elif f_score < 70.0:
            res_status = "TECHNICALLY_RELEVANT"
            overall_res = "HIGH_SIMILARITY"
        else:
            res_status = "TECHNICALLY_RELEVANT"
            overall_res = "ANTICIPATED"

        if temporal_status in ["PUBLISHED_AFTER_REFERENCE", "EARLIER_PRIORITY_BUT_PUBLISHED_AFTER"]:
            res_status = f"{res_status}_PUBLISHED_LATER"

        has_verified_ev = sc.get("evidence_score", 0.0) > 0.0 and any(item.get("verified") for item in sc.get("evidence_items", []))
        if not has_verified_ev:
            ev_conf_conclusion = "NOT VERIFIED — Specification text unavailable or 0 evidence quotes verified."
            ev_status_lbl = "Limited evidence (0% verified)"
            # Clamp unverified evidence confidence between 10.0 and 25.0 so a valid non-zero float is sent to the frontend
            ev_conf_val = round(max(10.0, min(25.0, sc.get("confidence_score", 20.0))), 1)
        else:
            ev_conf_conclusion = pair_analysis.get("evidence_confidence_conclusion") or f"Evidence confidence is {conf_score}% based on specification text verification."
            ev_status_lbl = sc.get("evidence_status_label", "Claim evidence verified")
            ev_conf_val = conf_score

        tech_rel_conclusion = pair_analysis.get("technical_relevance_conclusion") or f"Technical feature overlap is {sc.get('raw_feature_coverage', 0.0)}% across {sc.get('matched_feature_count', 0)} matching limitations."
        legal_disclaimer = pair_analysis.get("legal_assessment_disclaimer") or "Preliminary AI screening only. Legal patentability is not determined by AI and requires formal patent attorney examination."

        # Per-candidate Provenance Determination
        pat_num_str = (pat.patent_number or "").strip()
        if pat_num_str in live_retrieved_set or (pat.source_status == "LIVE_API" and (pat.source_type or "").upper() == "THE LENS" and pat_retrieved > 0):
            item_source_status = "LIVE_API"
            item_source_name = "The Lens Patent API"
            item_source_type = "THE LENS"
            item_retrieval_status = "LIVE_API_SUCCESS"
            doc_type_val = pat.document_type or "PATENT"
        elif pat.source_status == "FALLBACK" or (pat.source_type and "USPTO" in pat.source_type.upper()):
            item_source_status = "FALLBACK"
            item_source_name = "PatentsView API (Fallback)"
            item_source_type = pat.source_type or "USPTO"
            item_retrieval_status = "FALLBACK_SUCCESS"
            doc_type_val = pat.document_type or "PATENT"
        elif (pat.source_type and "ARXIV" in pat.source_type.upper()) or pat_num_str.startswith("ARXIV"):
            item_source_status = "LIVE_API"
            item_source_name = "arXiv Open Feed"
            item_source_type = "arXiv"
            item_retrieval_status = "LIVE_API_SUCCESS"
            doc_type_val = "NON-PATENT LITERATURE"
        else:
            item_source_status = "DATABASE"
            item_source_name = "Database Repository"
            item_source_type = "DATABASE"
            item_retrieval_status = "DATABASE_REPOSITORY"
            doc_type_val = "DATABASE RECORD" if (not pat.document_type or pat.document_type in ["PATENT", "DATABASE RECORD"]) else pat.document_type

        pat_out_obj = PatentOut.model_validate(pat)
        pat_out_obj.source_status = item_source_status
        pat_out_obj.source_name = item_source_name
        pat_out_obj.retrieval_status = item_retrieval_status
        pat_out_obj.source_type = item_source_type
        pat_out_obj.document_type = doc_type_val

        matched_feat_count = sc.get("matched_feature_count") if sc.get("matched_feature_count") is not None else (len(pair_analysis.get("matched_features", [])) or (len(sc.get("strong_matches", [])) + len(sc.get("partial_matches", []))))
        total_feat_count = sc.get("total_feature_count") if sc.get("total_feature_count") is not None else (len(gemini_features) or len(sc.get("target_atomic_features", [])) or 5)

        # Requirement 11: If a candidate has zero verified technical feature matches, classify clearly as LOW TECHNICAL SIMILARITY / candidate only
        if matched_feat_count == 0:
            relevance_level = "LOW TECHNICAL SIMILARITY (Candidate Only)"
            res_status = "LOW_TECHNICAL_SIMILARITY"
            sem_label = "Low"
        else:
            sem_label = get_similarity_level_label(sc["semantic_score"])

        # Requirement 12: If evidence is unavailable, show Evidence: UNAVAILABLE
        c_status = sc.get("claims_status", "AVAILABLE" if (pat.claims and len(pat.claims) > 20) else "NOT_AVAILABLE")
        f_status = sc.get("full_text_status", "AVAILABLE" if (pat.description and len(pat.description) > 100) else "NOT_AVAILABLE")
        if c_status == "NOT_AVAILABLE" and f_status == "NOT_AVAILABLE":
            ev_status_lbl = "Evidence: UNAVAILABLE"
            ev_status = "UNAVAILABLE"
            ev_avail_lvl = "NOT_AVAILABLE"
        else:
            ev_avail_lvl = sc.get("evidence_availability_level", "NOT_VERIFIABLE")

        sri_item = SearchResultItem(
            patent=pat_out_obj,
            semantic_score=sc["semantic_score"],
            keyword_score=sc["keyword_score"],
            domain_score=sc["domain_score"],
            final_score=sc["final_score"],
            confidence_score=ev_conf_val,
            matched_concepts=sc["matched_concepts"],
            rank=idx,
            semantic_similarity_label=sem_label,
            relevance_explanation=pair_analysis.get("relevance_explanation"),
            feature_comparison=pair_analysis.get("feature_comparison", []),
            patent_specific_insights=pair_analysis.get("patent_specific_insights", []),
            technical_features=pair_analysis.get("technical_features", gemini_features),
            essential_features=gemini_essential,
            optional_features=gemini_optional,
            structured_quadruplets=gemini_quads,
            distinctive_features=pair_analysis.get("distinctive_features", []),
            matched_features=pair_analysis.get("matched_features", []),
            strong_matches=sc.get("strong_matches", []),
            partial_matches=sc.get("partial_matches", []),
            weak_matches=sc.get("weak_matches", []),
            missing_features=sc.get("missing_features", []),
            unmatched_features=pair_analysis.get("unmatched_features", sc.get("missing_features", [])),
            unverifiable_features=sc.get("unverifiable_features", []),
            evidence_items=sc.get("evidence_items", []),
            evidence_status_label=ev_status_lbl,
            overlap_summary=pair_analysis.get("overlap_summary"),
            claim_elements=pair_analysis.get("claim_elements", []),
            single_document_anticipation=pair_analysis.get("single_document_anticipation", "NO"),
            missing_elements=pair_analysis.get("missing_elements", []),
            technical_feature_coverage=sc["keyword_score"],
            evidence_confidence=ev_conf_val,
            overall_result=overall_res,
            score_breakdown=score_bd_obj,
            family_members=[
                PatentFamilyMember(
                    patent_number=pat.patent_number,
                    jurisdiction=pat.jurisdiction or "US",
                    kind="A1",
                    title=pat.title,
                    publication_date=pat.publication_date,
                    document_type=doc_type_val,
                    source_url=pat.source_url or ""
                )
            ],
            family_size=getattr(pat, "simple_family_size", 1) or 1,
            is_family_representative=True,
            family_id=getattr(pat, "simple_family_id", pat.patent_number) or pat.patent_number,
            temporal_status=temporal_status,
            result_status=res_status,
            relevance_level=relevance_level,
            evidence_status=ev_status,
            evidence_availability_level=ev_avail_lvl,
            source_status=item_source_status,
            source_name=item_source_name,
            retrieval_status=item_retrieval_status,
            feature_match_status=sc.get("feature_match_status", "PARTIAL"),
            feature_match_source=sc.get("feature_match_source", "ABSTRACT/TITLE"),
            raw_feature_coverage=round(((matched_feat_count) / (total_feat_count if total_feat_count > 0 else 1)) * 100.0, 1),
            weighted_technical_score=sc.get("weighted_technical_score", sc["keyword_score"]),
            matched_feature_count=matched_feat_count,
            total_feature_count=total_feat_count,
            claims_status=c_status,
            full_text_status=f_status,
            has_abstract=bool(pat.abstract and len(pat.abstract) > 10),
            has_claims=bool(pat.claims and len(pat.claims) > 20),
            has_description=bool(pat.description and len(pat.description) > 50),
            has_full_text=bool(pat.description and len(pat.description) > 50 and pat.claims and len(pat.claims) > 20),
            score_cap=sb_dict.get("score_cap"),
            score_cap_reason=sb_dict.get("score_cap_reason"),
            verification_status="VERIFIED" if (ev_status == "VERIFIED" and has_verified_ev) else "NOT_VERIFIED",
            data_quality_status=getattr(pat, "data_quality_status", "LIMITED") or "LIMITED",
            technical_relevance_conclusion=tech_rel_conclusion,
            evidence_confidence_conclusion=ev_conf_conclusion,
            temporal_status_conclusion=temporal_conclusion,
            legal_assessment_disclaimer=legal_disclaimer
        )

        result_items_response.append(sri_item)

        sr = SearchResult(
            search_id=search_record.id,
            patent_id=pat.id,
            semantic_score=sc["semantic_score"],
            keyword_score=sc["keyword_score"],
            domain_score=sc["domain_score"],
            final_score=sc["final_score"],
            matched_concepts=sc["matched_concepts"],
            rank=idx,
            analysis_payload=sri_item.model_dump(mode="json")
        )
        try:
            db.add(sr)
            db.commit()
        except Exception:
            pass

    # Save search record and embedded results to MongoDB Atlas SearchDoc
    try:
        from app.models.models import SearchDoc, SearchResultItem as MongoSRI
        import asyncio

        mongo_sris = []
        for sri in result_items_response:
            try:
                mongo_sris.append(
                    MongoSRI(
                        id=str(sri.patent.id),
                        patent_id=str(sri.patent.id),
                        semantic_score=sri.semantic_score,
                        keyword_score=sri.keyword_score,
                        domain_score=sri.domain_score,
                        final_score=sri.final_score,
                        matched_concepts=sri.matched_concepts or [],
                        rank=sri.rank,
                        analysis_payload=sri.model_dump(mode="json")
                    )
                )
            except Exception:
                pass

        s_doc = SearchDoc(
            id=str(search_record.id),
            user_id=str(current_user.id),
            invention_title=request.title,
            domain=request.domain,
            problem_statement=request.problem_statement,
            description=request.description,
            keywords=request.keywords,
            risk_level=risk_info["risk_level"],
            highest_similarity=highest_similarity,
            total_results=total_matches_count,
            very_high_similarity=vhigh_count,
            high_similarity=high_count,
            moderate_similarity=mod_count,
            low_similarity=low_count,
            patents_searched=pat_searched,
            patents_retrieved=pat_retrieved,
            patents_shortlisted=pat_shortlisted,
            patents_deeply_analyzed=pat_deeply_analyzed,
            pipeline_metrics=pipeline_metrics.model_dump(mode="json"),
            results=mongo_sris
        )
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(s_doc.insert())
        except Exception:
            asyncio.run(s_doc.insert())
        logger.info(f"✅ Successfully persisted SearchDoc '{search_record.id}' to MongoDB Atlas!")
    except Exception as e_mongo_save:
        logger.warning(f"MongoDB SearchDoc save note: {e_mongo_save}")


    summary = SearchSummary(
        total_results=total_matches_count,
        high_similarity=high_count,
        moderate_similarity=mod_count,
        low_similarity=low_count,
        very_high_similarity=vhigh_count,
        patents_searched=pat_searched,
        patents_retrieved=pat_retrieved,
        patents_shortlisted=pat_shortlisted,
        patents_deeply_analyzed=pat_deeply_analyzed,
        highest_semantic_similarity=highest_semantic_similarity,
        unique_families_count=len(family_grouped),
        pipeline_metrics=pipeline_metrics
    )

    try:
        def _do_novelty():
            return getattr(llm_service, "generate_novelty_analysis", lambda **k: None)(
                invention_title=request.title,
                problem_statement=request.problem_statement,
                description=request.description,
                matched_patents=[
                    {
                        "patent_number": item["patent"].patent_number,
                        "title": item["patent"].title,
                        "abstract": item["patent"].abstract,
                        "final_score": item["scores"]["final_score"]
                    }
                    for item in top_10
                ],
                risk_level=risk_info["risk_level"]
            )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as nov_pool:
            nov_fut = nov_pool.submit(_do_novelty)
            ai_analysis = nov_fut.result(timeout=1.5)
    except Exception as e_nov:
        logger.warning(f"[SEARCH ROUTE] Novelty analysis route timeout/note ({e_nov}). Using fallback summary.")
        ai_analysis = getattr(llm_service, "_generate_fallback_summary", lambda **k: None)(
            invention_title=request.title,
            risk_level=risk_info["risk_level"],
            matched_patents=[{"title": item["patent"].title} for item in top_10]
        )

    if pat_retrieved > 0:
        active_data_source = "The Lens Patent API (Live API)"
    elif lens_status == "LENS_RATE_LIMITED":
        active_data_source = "Database Repository (Lens API HTTP 429 Rate Limited / Monthly Quota Exceeded)"
    elif lens_status == "LENS_AUTH_ERROR":
        active_data_source = "Database Repository (Lens API HTTP Authorization Error)"
    elif lens_status == "LENS_API_UNAVAILABLE":
        active_data_source = "Database Repository (Lens API Unavailable / Network Timeout)"
    elif lens_api_service.is_configured:
        active_data_source = "Database Repository (Lens API 0 Live Records)"
    else:
        active_data_source = "Database Repository"
    active_ai_model = getattr(llm_service, "model_name", "Gemini 3.6 Flash")

    return PriorArtSearchResponse(
        search_id=search_record.id,
        invention_title=search_record.invention_title,
        domain=search_record.domain,
        created_at=search_record.created_at,
        risk_level=risk_info["risk_level"],
        risk_label=risk_info["label"],
        highest_similarity=highest_similarity,
        highest_semantic_similarity=highest_semantic_similarity,
        summary=summary,
        results=result_items_response,
        ai_analysis=ai_analysis,
        is_demo_dataset=True,
        data_source=active_data_source,
        ai_model_used=active_ai_model
    )

@router.get("/history", response_model=List[SearchHistoryItem])
def get_user_search_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve search history for the authenticated user."""
    searches = []
    try:
        searches = (
            db.query(Search)
            .filter(Search.user_id == current_user.id)
            .order_by(Search.created_at.desc())
            .all()
        )
    except Exception:
        pass

    if searches:
        return [SearchHistoryItem.model_validate(s) for s in searches]

    # Fallback to MongoDB SearchDoc
    try:
        from app.models.models import SearchDoc
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            mongo_searches = loop.run_until_complete(
                SearchDoc.find(SearchDoc.user_id == current_user.id).sort("-created_at").to_list()
            )
        except Exception:
            mongo_searches = asyncio.run(
                SearchDoc.find(SearchDoc.user_id == current_user.id).sort("-created_at").to_list()
            )

        if mongo_searches:
            history_list = []
            for ms in mongo_searches:
                history_list.append(
                    SearchHistoryItem(
                        id=str(ms.id),
                        invention_title=ms.invention_title,
                        domain=ms.domain,
                        risk_level=ms.risk_level,
                        highest_similarity=ms.highest_similarity,
                        total_results=ms.total_results,
                        created_at=ms.created_at
                    )
                )
            return history_list
    except Exception:
        pass

    return []

@router.get("/{search_id}", response_model=PriorArtSearchResponse)
async def get_search_details(
    search_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve search results by search_id."""
    import logging
    logger = logging.getLogger("patentlens.search")

    search = None
    if db:
        try:
            search = db.query(Search).filter(Search.id == search_id).first()
        except Exception:
            pass

    if not search:
        # Fallback to MongoDB SearchDoc
        try:
            from app.models.models import SearchDoc
            mongo_s = await SearchDoc.find_one(SearchDoc.id == search_id)

            if mongo_s:
                res_items = []
                for r_sub in mongo_s.results:
                    if r_sub.analysis_payload and isinstance(r_sub.analysis_payload, dict):
                        try:
                            res_items.append(SearchResultItem.model_validate(r_sub.analysis_payload))
                        except Exception:
                            pass

                risk_info = classify_prior_art_risk(mongo_s.highest_similarity)
                pipe_metrics_obj = None
                if mongo_s.pipeline_metrics:
                    try:
                        from app.schemas.schemas import PipelineMetrics
                        pipe_metrics_obj = PipelineMetrics.model_validate(mongo_s.pipeline_metrics)
                    except Exception:
                        pass

                summary = SearchSummary(
                    total_results=mongo_s.total_results,
                    high_similarity=mongo_s.high_similarity,
                    moderate_similarity=mongo_s.moderate_similarity,
                    low_similarity=mongo_s.low_similarity,
                    very_high_similarity=mongo_s.very_high_similarity,
                    patents_searched=mongo_s.patents_searched,
                    patents_retrieved=mongo_s.patents_retrieved,
                    patents_shortlisted=mongo_s.patents_shortlisted,
                    patents_deeply_analyzed=mongo_s.patents_deeply_analyzed,
                    highest_semantic_similarity=mongo_s.highest_similarity,
                    pipeline_metrics=pipe_metrics_obj
                )

                return PriorArtSearchResponse(
                    search_id=str(mongo_s.id),
                    invention_title=mongo_s.invention_title,
                    domain=mongo_s.domain,
                    created_at=mongo_s.created_at,
                    risk_level=mongo_s.risk_level,
                    risk_label=risk_info["label"],
                    highest_similarity=mongo_s.highest_similarity,
                    highest_semantic_similarity=mongo_s.highest_similarity,
                    summary=summary,
                    results=res_items,
                    is_demo_dataset=True,
                    data_source="Database Repository (MongoDB)",
                    ai_model_used="Gemini 3.5 Flash"
                )
        except Exception as e_mget:
            logger.warning(f"MongoDB search details fallback note: {e_mget}")

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search record not found.")

    results_db = (
        db.query(SearchResult)
        .filter(SearchResult.search_id == search.id)
        .order_by(SearchResult.rank.asc())
        .all()
    )


    llm_service = get_llm_service()
    result_items = []
    high_count = 0
    mod_count = 0
    low_count = 0
    vhigh_count = 0

    for r in results_db:
        f_score = r.final_score
        r_level = classify_prior_art_risk(f_score)["risk_level"]
        if r_level == "VERY HIGH":
            vhigh_count += 1
        elif r_level == "HIGH":
            high_count += 1
        elif r_level == "MODERATE":
            mod_count += 1
        else:
            low_count += 1

        if r.analysis_payload and isinstance(r.analysis_payload, dict):
            try:
                item_obj = SearchResultItem.model_validate(r.analysis_payload)
                result_items.append(item_obj)
                continue
            except Exception as e_payload:
                logger.warning(f"Error parsing saved analysis_payload for patent {r.patent_id}: {e_payload}")

        try:
            from app.services.gemini_service import gemini_service
        except ImportError:
            from app.services.gemini_service import gemini_service
        pair_analysis = gemini_service._normalize_parsed_response(
            gemini_service._generate_heuristic_pair_analysis(
                target_title=search.invention_title,
                target_description=search.description,
                patent_number=r.patent.patent_number,
                patent_title=r.patent.title,
                patent_abstract=r.patent.abstract,
                similarity_score=f_score,
                patent_description=r.patent.description or ""
            )
        )

        pat_obj = r.patent
        pat_num_str = (pat_obj.patent_number or "").strip()
        if (search.patents_retrieved or 0) > 0 and pat_obj.source_status == "LIVE_API" and (pat_obj.source_type or "").upper() == "THE LENS":
            item_src_status = "LIVE_API"
            item_src_name = "The Lens Patent API"
            item_src_type = "THE LENS"
            item_ret_status = "LIVE_API_SUCCESS"
            doc_type_val = pat_obj.document_type or "PATENT"
        elif pat_obj.source_status == "FALLBACK" or (pat_obj.source_type and "USPTO" in pat_obj.source_type.upper()):
            item_src_status = "FALLBACK"
            item_src_name = "PatentsView API (Fallback)"
            item_src_type = pat_obj.source_type or "USPTO"
            item_ret_status = "FALLBACK_SUCCESS"
            doc_type_val = pat_obj.document_type or "PATENT"
        elif (pat_obj.source_type and "ARXIV" in pat_obj.source_type.upper()) or pat_num_str.startswith("ARXIV"):
            item_src_status = "LIVE_API"
            item_src_name = "arXiv Open Feed"
            item_src_type = "arXiv"
            item_ret_status = "LIVE_API_SUCCESS"
            doc_type_val = "NON-PATENT LITERATURE"
        else:
            item_src_status = "DATABASE"
            item_src_name = "Database Repository"
            item_src_type = "DATABASE"
            item_ret_status = "DATABASE_REPOSITORY"
            doc_type_val = "DATABASE RECORD" if (not pat_obj.document_type or pat_obj.document_type in ["PATENT", "DATABASE RECORD"]) else pat_obj.document_type

        pat_out = PatentOut.model_validate(pat_obj)
        pat_out.source_status = item_src_status
        pat_out.source_name = item_src_name
        pat_out.source_type = item_src_type
        pat_out.retrieval_status = item_ret_status
        pat_out.document_type = doc_type_val

        result_items.append(
            SearchResultItem(
                patent=pat_out,
                semantic_score=r.semantic_score,
                keyword_score=r.keyword_score,
                domain_score=r.domain_score,
                final_score=r.final_score,
                matched_concepts=r.matched_concepts or [],
                rank=r.rank,
                semantic_similarity_label=get_similarity_level_label(r.semantic_score),
                relevance_explanation=pair_analysis.get("relevance_explanation"),
                feature_comparison=pair_analysis.get("feature_comparison", []),
                patent_specific_insights=pair_analysis.get("patent_specific_insights", []),
                technical_features=pair_analysis.get("technical_features", []),
                distinctive_features=pair_analysis.get("distinctive_features", []),
                matched_features=pair_analysis.get("matched_features", []),
                unmatched_features=pair_analysis.get("unmatched_features", []),
                overlap_summary=pair_analysis.get("overlap_summary"),
                claim_elements=pair_analysis.get("claim_elements", []),
                single_document_anticipation=pair_analysis.get("single_document_anticipation", "NO"),
                missing_elements=pair_analysis.get("missing_elements", []),
                technical_feature_coverage=pair_analysis.get("technical_feature_coverage", 0.0),
                evidence_confidence=pair_analysis.get("evidence_confidence", 0.0),
                overall_result=pair_analysis.get("overall_result", "NON_ANTICIPATED"),
                source_status=item_src_status,
                source_name=item_src_name,
                retrieval_status=item_ret_status
            )
        )

    risk_info = classify_prior_art_risk(search.highest_similarity)
    highest_semantic = max((r.semantic_score for r in result_items), default=0.0)

    vhigh_val = vhigh_count
    high_val = high_count
    mod_val = mod_count
    low_val = low_count
    tot_val = vhigh_val + high_val + mod_val + low_val

    pipe_metrics_obj = None
    if search.pipeline_metrics:
        try:
            from app.schemas.schemas import PipelineMetrics
            import json
            pm_data = json.loads(search.pipeline_metrics) if isinstance(search.pipeline_metrics, str) else search.pipeline_metrics
            if isinstance(pm_data, dict):
                pipe_metrics_obj = PipelineMetrics.model_validate(pm_data)
        except Exception as e_pm:
            logger.warning(f"Error parsing pipeline_metrics: {e_pm}")

    summary = SearchSummary(
        total_results=tot_val,
        high_similarity=high_val,
        moderate_similarity=mod_val,
        low_similarity=low_val,
        very_high_similarity=vhigh_val,
        patents_searched=int(search.patents_searched or tot_val),
        patents_retrieved=int(search.patents_retrieved or 0),
        patents_shortlisted=int(search.patents_shortlisted or tot_val),
        patents_deeply_analyzed=int(search.patents_deeply_analyzed or tot_val),
        highest_semantic_similarity=highest_semantic,
        pipeline_metrics=pipe_metrics_obj
    )

    active_data_source = "The Lens Patent API (Live API)" if (search.patents_retrieved or 0) > 0 else "Database Repository"
    active_ai_model = getattr(llm_service, "model_name", "Gemini 2.5 Flash")

    return PriorArtSearchResponse(
        search_id=str(search.id),
        invention_title=str(search.invention_title),
        domain=str(search.domain),
        created_at=search.created_at,
        risk_level=risk_info["risk_level"],
        risk_label=risk_info["label"],
        highest_similarity=float(search.highest_similarity),
        highest_semantic_similarity=highest_semantic,
        summary=summary,
        results=result_items,
        is_demo_dataset=True,
        data_source=active_data_source,
        ai_model_used=active_ai_model
    )

@router.delete("/{search_id}")
async def delete_search_record(
    search_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a search record belonging to the authenticated user."""
    deleted = False
    try:
        from app.models.models import SearchDoc
        search_doc = await SearchDoc.find_one(SearchDoc.id == search_id)
        if search_doc:
            if search_doc.user_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access.")
            await search_doc.delete()
            deleted = True
    except HTTPException:
        raise
    except Exception:
        pass

    if db:
        search = db.query(Search).filter(Search.id == search_id).first()
        if search:
            if search.user_id != current_user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access.")
            db.delete(search)
            db.commit()
            deleted = True

    if deleted:
        return {"success": True, "message": "Search record successfully deleted."}

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search record not found.")
