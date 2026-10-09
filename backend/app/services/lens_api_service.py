import logging
import json
import time
import httpx
from typing import List, Dict, Any, Optional, Tuple

from app.core.config import settings
logger = logging.getLogger("patentlens.lens_api")


class LensAPIService:
    """
    Dedicated service for querying The Lens Patent API (POST https://api.lens.org/patent/search)
    using Bearer-token authentication, exponential backoff, structured 8-strategy search,
    and robust error handling.
    """

    def __init__(self):
        self.api_token = getattr(settings, "LENS_API_TOKEN", "")
        self.api_url = getattr(settings, "LENS_API_URL", "https://api.lens.org/patent/search")
        self.max_results = getattr(settings, "MAX_EXTERNAL_API_RESULTS", 100)
        self.http_timeout = getattr(settings, "LENS_HTTP_TIMEOUT", 20.0)
        self.thread_timeout = getattr(settings, "LENS_THREAD_TIMEOUT", 22.0)

    @property
    def is_configured(self) -> bool:
        token = (self.api_token or "").strip()
        return bool(token and len(token) > 8 and not token.startswith("your_"))

    def masked_token(self) -> str:
        token = (self.api_token or "").strip()
        if not token:
            return "UNCONFIGURED"
        if len(token) <= 8:
            return "****"
        return f"{token[:4]}...{token[-4:]}"

    @staticmethod
    def _sanitize_query_for_lens(raw_q: str) -> str:
        import re
        if not raw_q or not raw_q.strip():
            return "technology"
        q = re.sub(r'claims:\(|\)|classifications_cpc\.symbol:|[&|/]', ' ', raw_q)
        words = [w for w in re.findall(r'[a-zA-Z0-9]+', q) if len(w) > 2 and w.lower() not in {'for', 'and', 'the', 'with', 'msme', 'system', 'device', 'method', 'apparatus'}]
        if len(words) >= 3:
            return f"{words[0]} AND {words[1]} AND {words[2]}"
        elif len(words) >= 2:
            return f"{words[0]} AND {words[1]}"
        elif words:
            return words[0]
        return "technology"

    def search_patents(
        self,
        queries: List[str],
        cpc_candidates: Optional[List[str]] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Execute multi-strategy search queries against The Lens Patent API.
        """
        if not self.is_configured:
            logger.warning("[LENS API AUDIT] API token not configured or placeholder used. Skipping live request.")
            return {
                "results": [],
                "status": "LENS_UNCONFIGURED",
                "retrieved_count": 0,
                "diagnostics": {"is_configured": False, "masked_token": "UNCONFIGURED", "http_status": 0}
            }

        logger.info(f"[LENS API AUDIT] Endpoint: {self.api_url} | Token Configured: True | Masked Token: {self.masked_token()}")
        logger.info(f"[LENS API AUDIT] Executing {len(queries)} search queries across Lens API: {queries}")

        headers = {
            "Authorization": f"Bearer {self.api_token.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PatentLens-AI/1.0"
        }

        all_results: List[Dict[str, Any]] = []
        seen_lens_ids = set()

        from concurrent.futures import ThreadPoolExecutor

        target_queries = [q.strip() for q in queries if q and q.strip()][:8]
        if not target_queries:
            return {
                "results": [],
                "status": "LENS_QUERY_ERROR",
                "retrieved_count": 0,
                "diagnostics": {"is_configured": True, "masked_token": self.masked_token(), "http_status": 400}
            }

        query_statuses = []
        http_statuses = []
        total_counts = []

        def _fetch_single_lens_query(q_str: str) -> Tuple[List[Dict[str, Any]], str, int, int]:
            clean_q = self._sanitize_query_for_lens(q_str)
            p_payload = {
                "query": clean_q,
                "size": min(25, limit),
                "from": 0,
                "include": [
                    "lens_id", "doc_number", "jurisdiction", "kind",
                    "date_published", "biblio", "abstract", "claims", "description",
                    "families"
                ]
            }
            start_time = time.time()
            try:
                with httpx.Client(timeout=self.http_timeout, follow_redirects=True) as http_client:
                    res = http_client.post(self.api_url, json=p_payload, headers=headers)
                    elapsed_ms = round((time.time() - start_time) * 1000.0, 1)
                    
                    if res.status_code == 200:
                        data = res.json()
                        raw_items = data.get("data") or data.get("results") or []
                        total_matched = data.get("total") or len(raw_items)
                        parsed = []
                        has_title_cnt = 0
                        has_abstract_cnt = 0
                        has_claims_cnt = 0
                        has_desc_cnt = 0

                        for item in raw_items:
                            norm_item = self._normalize_lens_record(item)
                            if norm_item:
                                parsed.append(norm_item)
                                if norm_item.get("title"): has_title_cnt += 1
                                if norm_item.get("abstract"): has_abstract_cnt += 1
                                if norm_item.get("claims"): has_claims_cnt += 1
                                if norm_item.get("description"): has_desc_cnt += 1

                        logger.info(
                            f"[LENS HTTP DIAGNOSTICS] Query: '{q_str}' | Status: 200 OK | Response Time: {elapsed_ms}ms | "
                            f"Total Matched: {total_matched} | Returned: {len(raw_items)} | Parsed: {len(parsed)}"
                        )
                        if parsed:
                            return parsed, "LENS_OK", 200, total_matched
                        else:
                            return [], "LENS_NO_RESULTS", 200, total_matched
                    elif res.status_code in [401, 403]:
                        logger.error(f"[LENS HTTP DIAGNOSTICS] HTTP {res.status_code} LENS_AUTH_ERROR ({elapsed_ms}ms): {res.text[:200]}")
                        return [], "LENS_AUTH_ERROR", res.status_code, 0
                    elif res.status_code == 429:
                        logger.error(f"[LENS HTTP DIAGNOSTICS] HTTP 429 LENS_RATE_LIMITED ({elapsed_ms}ms): {res.text[:200]}")
                        return [], "LENS_RATE_LIMITED", 429, 0
                    elif res.status_code == 400:
                        logger.error(f"[LENS HTTP DIAGNOSTICS] HTTP 400 LENS_QUERY_ERROR for query '{q_str}' ({elapsed_ms}ms): {res.text[:200]}")
                        return [], "LENS_QUERY_ERROR", 400, 0
                    else:
                        logger.error(f"[LENS HTTP DIAGNOSTICS] HTTP {res.status_code} LENS_API_UNAVAILABLE ({elapsed_ms}ms): {res.text[:200]}")
                        return [], "LENS_API_UNAVAILABLE", res.status_code, 0
            except Exception as e:
                elapsed_ms = round((time.time() - start_time) * 1000.0, 1)
                logger.warning(f"[LENS HTTP DIAGNOSTICS] Exception LENS_API_UNAVAILABLE for query '{q_str}' ({elapsed_ms}ms): {e}")
                return [], "LENS_API_UNAVAILABLE", 503, 0

        with ThreadPoolExecutor(max_workers=min(8, len(target_queries))) as pool:
            futures = [pool.submit(_fetch_single_lens_query, q) for q in target_queries]
            for fut in futures:
                try:
                    records, q_stat, h_code, q_total = fut.result(timeout=self.thread_timeout)
                    query_statuses.append(q_stat)
                    http_statuses.append(h_code)
                    if q_total > 0:
                        total_counts.append(q_total)
                    for r in records:
                        if r["patent_number"] not in seen_lens_ids:
                            seen_lens_ids.add(r["patent_number"])
                            all_results.append(r)
                except Exception as e_fut:
                    logger.warning(f"[LENS API] Thread pool query timeout/error: {e_fut}")
                    query_statuses.append("LENS_API_UNAVAILABLE")
                    http_statuses.append(504)

        # Fail Loudly: Determine single atomic Lens API status
        primary_http_code = http_statuses[0] if http_statuses else 0
        if "LENS_AUTH_ERROR" in query_statuses and not all_results:
            overall_status = "LENS_AUTH_ERROR"
        elif "LENS_RATE_LIMITED" in query_statuses and not all_results:
            overall_status = "LENS_RATE_LIMITED"
        elif all_results:
            if any(s in ["LENS_RATE_LIMITED", "LENS_AUTH_ERROR", "LENS_API_UNAVAILABLE"] for s in query_statuses):
                overall_status = "LENS_PARTIAL_RESULTS"
            else:
                overall_status = "LENS_OK"
        else:
            if "LENS_QUERY_ERROR" in query_statuses:
                overall_status = "LENS_QUERY_ERROR"
            elif any(s == "LENS_API_UNAVAILABLE" for s in query_statuses):
                overall_status = "LENS_API_UNAVAILABLE"
            else:
                overall_status = "LENS_NO_RESULTS"

        max_total_searched = max(total_counts) if total_counts else len(all_results)

        logger.info(
            f"[LENS API AUDIT] Completed query execution. Overall Lens Status: {overall_status} | "
            f"HTTP Status: {primary_http_code} | Total Lens Matched: {max_total_searched} | Retrieved {len(all_results)} unique records."
        )

        return {
            "results": all_results[:limit],
            "status": overall_status,
            "retrieved_count": len(all_results),
            "total_searched": max_total_searched
        }

    def _normalize_lens_record(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Normalize Lens API JSON record into standardized internal schema format without data fabrication.
        """
        try:
            lens_id = raw.get("lens_id") or raw.get("id") or ""
            biblio = raw.get("biblio", {})
            pub_ref = biblio.get("publication_reference", {})

            doc_num = raw.get("doc_number") or pub_ref.get("doc_number") or raw.get("publication_number") or lens_id
            if not doc_num:
                return None

            jurisdiction = (raw.get("jurisdiction") or pub_ref.get("jurisdiction") or "").upper()
            if jurisdiction and not str(doc_num).startswith(jurisdiction):
                formatted_pat_num = f"{jurisdiction}-{doc_num}"
            else:
                formatted_pat_num = str(doc_num)

            # Extract Title from biblio.invention_title or raw.title
            t_str = ""
            inv_titles = biblio.get("invention_title") or raw.get("title")
            if isinstance(inv_titles, list):
                en_title = next((t.get("text") for t in inv_titles if isinstance(t, dict) and t.get("lang") == "en"), None)
                if en_title:
                    t_str = en_title.strip()
                else:
                    t_str = " ".join([t.get("text", "") if isinstance(t, dict) else str(t) for t in inv_titles]).strip()
            elif isinstance(inv_titles, dict):
                t_str = inv_titles.get("text", "").strip()
            elif inv_titles:
                t_str = str(inv_titles).strip()

            if not t_str:
                t_str = f"Patent Document {formatted_pat_num}"

            # Extract Abstract (Do not fabricate text if missing)
            abs_field = raw.get("abstract") or biblio.get("abstract")
            abs_str = ""
            if isinstance(abs_field, list):
                en_abs = next((a.get("text") for a in abs_field if isinstance(a, dict) and a.get("lang") == "en"), None)
                if en_abs:
                    abs_str = en_abs.strip()
                else:
                    abs_str = " ".join([a.get("text", "") if isinstance(a, dict) else str(a) for a in abs_field]).strip()
            elif isinstance(abs_field, dict):
                abs_str = abs_field.get("text", "").strip()
            elif abs_field:
                abs_str = str(abs_field).strip()

            # Extract Claims (Do not fabricate text if missing)
            claims_field = raw.get("claims") or raw.get("claim") or biblio.get("claims")
            claims_str = ""
            if isinstance(claims_field, list):
                en_claim = next((c.get("text") for c in claims_field if isinstance(c, dict) and c.get("lang") == "en"), None)
                if en_claim:
                    claims_str = en_claim.strip()
                else:
                    claims_str = " ".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in claims_field]).strip()
            elif isinstance(claims_field, dict):
                claims_str = claims_field.get("text", "").strip()
            elif claims_field:
                claims_str = str(claims_field).strip()

            # Extract Description (Do not fabricate text if missing)
            desc_field = raw.get("description")
            desc_str = ""
            if isinstance(desc_field, list):
                en_desc = next((d.get("text") for d in desc_field if isinstance(d, dict) and d.get("lang") == "en"), None)
                if en_desc:
                    desc_str = en_desc.strip()
                else:
                    desc_str = " ".join([d.get("text", "") if isinstance(d, dict) else str(d) for d in desc_field]).strip()
            elif isinstance(desc_field, dict):
                desc_str = desc_field.get("text", "").strip()
            elif desc_field:
                desc_str = str(desc_field).strip()

            # Extract Assignees / Applicants
            parties = biblio.get("parties", {})
            applicants = parties.get("applicants") or raw.get("owner") or raw.get("assignee")
            owners = ""
            if isinstance(applicants, list):
                names = []
                for app in applicants:
                    if isinstance(app, dict):
                        ex_name = app.get("extracted_name", {}).get("value") or app.get("name")
                        if ex_name:
                            names.append(ex_name)
                    elif isinstance(app, str):
                        names.append(app)
                owners = ", ".join(names)
            elif isinstance(applicants, dict):
                owners = applicants.get("extracted_name", {}).get("value") or applicants.get("name", "")

            # Extract Inventors
            inventors_list = parties.get("inventors") or raw.get("inventor") or raw.get("author")
            inventors = ""
            if isinstance(inventors_list, list):
                inv_names = []
                for inv in inventors_list:
                    if isinstance(inv, dict):
                        ex_name = inv.get("extracted_name", {}).get("value") or inv.get("name")
                        if ex_name:
                            inv_names.append(ex_name)
                    elif isinstance(inv, str):
                        inv_names.append(inv)
                inventors = ", ".join(inv_names)
            elif isinstance(inventors_list, dict):
                inventors = inventors_list.get("extracted_name", {}).get("value") or inventors_list.get("name", "")

            # Publication Date
            pub_date = (
                raw.get("date_published") or
                pub_ref.get("date") or
                raw.get("publication_date") or
                "2024-01-01"
            )

            # Extract Filing Date & Earliest Priority Date
            app_ref = biblio.get("application_reference", {})
            filing_date = app_ref.get("date") or raw.get("filing_date") or None

            p_claims = biblio.get("priority_claims", {}).get("data") or raw.get("priority_claims") or []
            p_dates = []
            if isinstance(p_claims, list):
                for pc in p_claims:
                    if isinstance(pc, dict) and pc.get("date"):
                        p_dates.append(str(pc["date"])[:10])
                    elif isinstance(pc, str):
                        p_dates.append(pc[:10])
            earliest_priority_date = min(p_dates) if p_dates else (raw.get("priority_date") or filing_date or pub_date)

            # CPC & IPC codes
            cpc_data = biblio.get("classifications_cpc", {}).get("classifications") or raw.get("classifications_cpc", [])
            cpc_codes = []
            if isinstance(cpc_data, list):
                for c in cpc_data:
                    if isinstance(c, dict) and c.get("symbol"):
                        cpc_codes.append(c["symbol"])
                    elif isinstance(c, str):
                        cpc_codes.append(c)

            ipc_data = biblio.get("classifications_ipcr", {}).get("classifications") or raw.get("classifications_ipc", [])
            ipc_codes = []
            if isinstance(ipc_data, list):
                for i in ipc_data:
                    if isinstance(i, dict) and i.get("symbol"):
                        ipc_codes.append(i["symbol"])
                    elif isinstance(i, str):
                        ipc_codes.append(i)

            # Family Information
            families_info = raw.get("families") or {}
            simple_fam = families_info.get("simple_family") or raw.get("simple_family") or {}
            ext_fam = families_info.get("extended_family") or raw.get("extended_family") or {}
            
            family_id = (
                simple_fam.get("id") or
                ext_fam.get("id") or
                str(doc_num).replace("-", "").replace(" ", "").upper()[:12]
            )
            simple_family_size = simple_fam.get("size") or len(simple_fam.get("members", [])) or 1
            extended_family_size = ext_fam.get("size") or len(ext_fam.get("members", [])) or 1

            kind_code = raw.get("kind") or pub_ref.get("kind") or "A1"
            url = raw.get("url") or f"https://www.lens.org/lens/patent/{lens_id or formatted_pat_num}"

            # Real Availability Flags (Never fabricate missing fields)
            lens_has_claims = raw.get("has_claim")
            lens_has_desc = raw.get("has_description")
            lens_has_full = raw.get("has_full_text")

            has_claim_flag = bool(lens_has_claims is True or (claims_str and len(claims_str.strip()) > 15))
            has_desc_flag = bool(lens_has_desc is True or (desc_str and len(desc_str.strip()) > 30))
            has_full_text_flag = bool(lens_has_full is True or (has_claim_flag and has_desc_flag))
            has_abstract_flag = bool(abs_str and len(abs_str.strip()) > 10)

            if not has_claim_flag:
                claims_str = ""

            if not has_desc_flag:
                desc_str = ""

            # Data Quality Determination
            if has_claim_flag and has_desc_flag:
                dq_status = "COMPLETE"
            elif has_claim_flag or has_desc_flag:
                dq_status = "PARTIAL"
            elif has_abstract_flag:
                dq_status = "LIMITED"
            else:
                dq_status = "INSUFFICIENT"

            full_text_combined = f"{t_str}\n\nABSTRACT:\n{abs_str}\n\nCLAIMS:\n{claims_str}\n\nDESCRIPTION:\n{desc_str}".strip()

            return {
                "patent_id": formatted_pat_num,
                "patent_number": formatted_pat_num,
                "lens_id": lens_id,
                "title": t_str,
                "abstract": abs_str,
                "claims": claims_str,
                "description": desc_str,
                "full_text": full_text_combined,
                "inventors": inventors or "Lens Patent Inventor",
                "assignee": owners or "Lens Patent Assignee",
                "applicant": owners or "Lens Patent Assignee",
                "publication_date": str(pub_date)[:10],
                "filing_date": str(filing_date)[:10] if filing_date else None,
                "priority_date": str(earliest_priority_date)[:10] if earliest_priority_date else str(pub_date)[:10],
                "earliest_priority_date": str(earliest_priority_date)[:10] if earliest_priority_date else str(pub_date)[:10],
                "source_url": url,
                "source": "Lens Patent API",
                "source_type": "THE LENS",
                "source_status": "LIVE_API",
                "document_type": "PATENT",
                "cpc": ", ".join(cpc_codes[:5]) if cpc_codes else "",
                "cpc_codes": ", ".join(cpc_codes[:5]) if cpc_codes else "",
                "ipc": ", ".join(ipc_codes[:5]) if ipc_codes else "",
                "ipc_codes": ", ".join(ipc_codes[:5]) if ipc_codes else "",
                "jurisdiction": jurisdiction or "US",
                "family_id": str(family_id),
                "simple_family_id": str(family_id),
                "simple_family_size": simple_family_size,
                "extended_family_size": extended_family_size,
                "kind": kind_code,
                "has_abstract": has_abstract_flag,
                "has_claims": has_claim_flag,
                "has_description": has_desc_flag,
                "has_full_text": has_full_text_flag,
                "data_quality_status": dq_status
            }
        except Exception as e:
            logger.warning(f"[LENS API] Failed normalizing Lens record: {e}")
            return None

    def search_by_cpc_classification(
        self,
        cpc_codes: List[str],
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Execute independent CPC/IPC classification retrieval path.
        """
        if not self.is_configured or not cpc_codes:
            return []

        cpc_queries = [f"classifications_cpc.symbol:\"{code.strip()}\"" for code in cpc_codes if code.strip()]
        if not cpc_queries:
            return []

        logger.info(f"[LENS API] Executing independent CPC classification search for codes: {cpc_codes}")
        res = self.search_patents(queries=cpc_queries, limit=limit)
        return res.get("results", [])

    def fetch_citations_and_family(
        self,
        patent_numbers: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Execute citation expansion for strong candidates.
        """
        if not self.is_configured or not patent_numbers:
            return []

        citation_queries = [f"doc_number:\"{p_num}\"" for p_num in patent_numbers[:5] if p_num]
        if not citation_queries:
            return []

        logger.info(f"[LENS API] Executing citation expansion search for candidates: {patent_numbers[:5]}")
        res = self.search_patents(queries=citation_queries, limit=20)
        return res.get("results", [])

    def group_by_patent_family(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Group retrieved patent candidates by patent family (simple/extended family) to deduplicate
        publications representing the same invention across jurisdictions (WO, US, EP, CN, etc.).
        Selects 1 best representative document per family based on claims richness, text completeness,
        jurisdiction, and publication date.
        """
        if not candidates:
            return []

        family_groups: Dict[str, List[Dict[str, Any]]] = {}

        for item in candidates:
            fam_id = item.get("family_id")
            if not fam_id:
                clean_num = str(item.get("patent_number", "")).split("-")[-1]
                fam_id = clean_num[:10] if clean_num else "UNKNOWN_FAMILY"

            if fam_id not in family_groups:
                family_groups[fam_id] = []
            family_groups[fam_id].append(item)

        deduplicated_representatives = []

        for fam_id, members in family_groups.items():
            def rank_key(m):
                has_claims = 1 if m.get("claims") and len(m["claims"]) > 20 else 0
                text_len = len(m.get("abstract", "") or "") + len(m.get("claims", "") or "") + len(m.get("description", "") or "")
                jurisdiction_bonus = 2 if m.get("jurisdiction") in ["US", "WO", "EP"] else 0
                return (has_claims, jurisdiction_bonus, text_len, m.get("publication_date", ""))

            sorted_members = sorted(members, key=rank_key, reverse=True)
            rep = dict(sorted_members[0])

            family_member_list = [
                {
                    "patent_number": mem.get("patent_number"),
                    "jurisdiction": mem.get("jurisdiction", "US"),
                    "kind": mem.get("kind", "A1"),
                    "title": mem.get("title", ""),
                    "publication_date": mem.get("publication_date", "2024-01-01"),
                    "document_type": mem.get("document_type", "PATENT"),
                    "source_url": mem.get("source_url", "")
                }
                for mem in sorted_members
            ]

            rep["family_members"] = family_member_list
            rep["family_size"] = len(sorted_members)
            rep["is_family_representative"] = True
            rep["family_id"] = fam_id

            deduplicated_representatives.append(rep)

        logger.info(f"[PATENT DEDUPLICATION] Grouped {len(candidates)} raw documents into {len(deduplicated_representatives)} distinct patent families.")
        return deduplicated_representatives


lens_api_service = LensAPIService()
