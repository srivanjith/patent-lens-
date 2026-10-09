import logging
import json
import time
import httpx
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Patent
from ml.embedding_service import embedding_service
from ml.preprocessing import prepare_combined_text
from app.services.lens_api_service import lens_api_service
logger = logging.getLogger("patentlens.patent_api")


class PatentAPIService:
    """
    Orchestration service for fetching prior-art records:
    1. Primary Patent Retrieval: The Lens Patent API (POST https://api.lens.org/patent/search)
    2. Supplementary Patent Retrieval: PatentsView API (Fallback if Lens key unconfigured or results sparse)
    3. Separate Non-Patent Literature: arXiv API (Tagged as arXiv / NON-PATENT LITERATURE)
    """

    def __init__(self):
        self.api_key = getattr(settings, "PATENTS_API_KEY", "")
        self.provider = getattr(settings, "PATENTS_API_PROVIDER", "patentsview").lower()
        self.max_results = getattr(settings, "MAX_EXTERNAL_API_RESULTS", 100)

    def fetch_and_cache_external_patents(
        self,
        db: Session,
        title: str,
        keywords: List[str],
        domain: str,
        search_queries: Optional[List[str]] = None,
        cpc_candidates: Optional[List[str]] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Fetch external patents from The Lens Patent API (Primary) and non-patent literature
        from arXiv (Secondary), deduplicate, generate SBERT embeddings, and cache in DB.
        """
        logger.info(f"[PATENT API] Initiating search for title='{title}', domain='{domain}', queries={search_queries}")

        target_limit = min(limit, self.max_results)
        raw_candidates = []

        # Construct search queries if not provided
        queries = search_queries or []
        if not queries:
            query_terms = [k.strip() for k in (keywords or []) if len(k.strip()) > 2]
            if not query_terms and title:
                query_terms = [w.strip() for w in title.split() if len(w.strip()) > 3][:3]
            if not query_terms:
                query_terms = [domain or "technology"]
            queries = [" ".join(query_terms[:4])]

        import os
        from unittest.mock import Mock, MagicMock
        is_testing = (getattr(settings, "TESTING", False) or os.getenv("TESTING", "").lower() == "true") and not (getattr(settings, "LIVE_BENCHMARK", False) or os.getenv("LIVE_BENCHMARK", "").lower() == "true")
        is_mocked = "mock" in str(lens_api_service.search_patents).lower()

        lens_total_searched = 0
        lens_retrieved_count = 0
        lens_api_status = "LENS_UNCONFIGURED"

        if lens_api_service.is_configured:
            if is_testing and not is_mocked:
                logger.info("[PATENT API] TESTING mode active. Skipping live Lens API requests.")
                lens_api_status = "LENS_TESTING_MODE"
            else:
                logger.info("[PATENT API] Fetching primary patent candidates from The Lens Patent API...")
                lens_resp = lens_api_service.search_patents(
                    queries=queries,
                    cpc_candidates=cpc_candidates,
                    limit=target_limit
                )
                lens_patents = lens_resp.get("results", [])
                lens_api_status = lens_resp.get("status", "LENS_OK")
                lens_retrieved_count = lens_resp.get("retrieved_count", len(lens_patents))
                lens_total_searched = lens_resp.get("total_searched", 0)

                # Independent CPC/IPC Classification Retrieval Path
                if cpc_candidates:
                    cpc_patents = lens_api_service.search_by_cpc_classification(cpc_codes=cpc_candidates, limit=20)
                    lens_patents.extend(cpc_patents)

                # Apply Patent Family Deduplication
                dedup_lens_patents = lens_api_service.group_by_patent_family(lens_patents)
                raw_candidates.extend(dedup_lens_patents)
                logger.info(f"[PATENT API] Retained {len(dedup_lens_patents)} distinct patent families from The Lens (Open World Matched: {lens_total_searched}).")

        # 2. SUPPLEMENTARY SEARCH: PatentsView API if Lens returned < 10 records
        if not is_testing and len(raw_candidates) < 10:
            logger.info("[PATENT API] Querying supplementary patent records from PatentsView API...")
            supp_candidates = self._fetch_from_patentsview(title, keywords, domain, limit=target_limit - len(raw_candidates))
            for sc in supp_candidates:
                sc["source_status"] = "FALLBACK"
            raw_candidates.extend(supp_candidates)

        # 3. SEPARATE NON-PATENT LITERATURE: arXiv API
        if not is_testing:
            logger.info("[PATENT API] Fetching non-patent literature from arXiv Open Feed...")
            arxiv_records = self._fetch_from_arxiv(title, keywords, domain, limit=15)
            for ar in arxiv_records:
                ar["source_status"] = "LIVE_API"
            raw_candidates.extend(arxiv_records)

        logger.info(f"[PATENT API] Total combined candidate records retrieved: {len(raw_candidates)}")

        # 4. Deduplicate, Generate Batch SBERT Embeddings, and Cache in DB
        try:
            from ml.preprocessing import prepare_weighted_patent_text
        except ImportError:
            from ml.preprocessing import prepare_weighted_patent_text
        newly_cached_patents = []
        skipped_count = 0

        # Bulk DB check for existing patents
        all_pat_nums = [item.get("patent_number", "").strip() for item in raw_candidates if item.get("patent_number", "").strip()]
        existing_pat_set = set()
        if all_pat_nums:
            existing_rows = db.query(Patent.patent_number).filter(Patent.patent_number.in_(all_pat_nums)).all()
            existing_pat_set = {r[0] for r in existing_rows}

        items_to_process = []
        texts_to_embed = []

        for item in raw_candidates:
            pat_num = item.get("patent_number", "").strip()
            if not pat_num or pat_num in existing_pat_set:
                skipped_count += 1
                continue

            pat_title = (item.get("title") or title or "Untitled Invention Record").strip()
            pat_abstract = (item.get("abstract") or f"Prior art publication {pat_num} in domain {domain}.").strip()
            pat_claims = (item.get("claims") or "").strip()
            pat_desc = (item.get("description") or "").strip()

            text_for_embedding = prepare_weighted_patent_text(
                title=pat_title,
                abstract=pat_abstract,
                claims=pat_claims,
                description=pat_desc
            )
            items_to_process.append((item, pat_num, pat_title, pat_abstract, pat_claims, pat_desc))
            texts_to_embed.append(text_for_embedding)

        embeddings = []
        if texts_to_embed:
            try:
                embeddings = embedding_service.generate_embeddings(texts_to_embed)
            except Exception:
                embeddings = [embedding_service.generate_embedding(t) for t in texts_to_embed]

        for idx, (item, pat_num, pat_title, pat_abstract, pat_claims, pat_desc) in enumerate(items_to_process):
            emb = embeddings[idx] if idx < len(embeddings) else []
            pat_inventors = item.get("inventors") or "Independent Author"
            pat_assignee = item.get("assignee") or "Independent Institution"
            pat_date = item.get("publication_date") or "2024-01-01"
            pat_url = item.get("source_url") or f"https://patents.google.com/patent/{pat_num}/en"
            source_type = item.get("source_type") or "THE LENS"
            source_status = item.get("source_status") or "LIVE_API"
            doc_type = item.get("document_type") or "PATENT"

            new_patent = Patent(
                patent_number=pat_num,
                lens_id=item.get("lens_id"),
                title=pat_title,
                abstract=pat_abstract,
                claims=pat_claims,
                description=pat_desc,
                inventors=pat_inventors,
                assignee=pat_assignee,
                publication_date=pat_date,
                filing_date=item.get("filing_date"),
                earliest_priority_date=item.get("earliest_priority_date") or pat_date,
                simple_family_id=item.get("simple_family_id") or item.get("family_id"),
                simple_family_size=item.get("simple_family_size", 1),
                extended_family_size=item.get("extended_family_size", 1),
                data_quality_status=item.get("data_quality_status", "LIMITED"),
                domain=domain or "Technology",
                source_url=pat_url,
                source_type=source_type,
                source_status=source_status,
                document_type=doc_type,
                cpc_codes=item.get("cpc_codes", ""),
                ipc_codes=item.get("ipc_codes", ""),
                jurisdiction=item.get("jurisdiction", "US"),
                embedding=json.dumps(emb) if isinstance(emb, list) else emb
            )
            db.add(new_patent)
            newly_cached_patents.append(new_patent)

        if newly_cached_patents:
            db.commit()
            logger.info(f"[PATENT API] Successfully cached {len(newly_cached_patents)} new records into database.")

        total_db_patents = db.query(Patent).count()
        final_patents_searched = lens_retrieved_count if (lens_retrieved_count and lens_retrieved_count > 0) else len(raw_candidates)
        live_patent_numbers = [item.get("patent_number", "").strip() for item in raw_candidates if item.get("source_status") == "LIVE_API" and item.get("patent_number", "").strip()]

        return {
            "patents_retrieved": lens_retrieved_count if lens_api_service.is_configured else 0,
            "patents_newly_cached": len(newly_cached_patents),
            "patents_skipped_duplicates": skipped_count,
            "patents_searched": final_patents_searched,
            "lens_total_searched": lens_total_searched,
            "lens_api_status": lens_api_status,
            "live_patent_numbers": live_patent_numbers
        }

    def execute_citation_expansion(
        self,
        db: Session,
        top_patent_numbers: List[str]
    ) -> List[Dict[str, Any]]:
        """Fetch backward/forward citations and related family members for top candidates."""
        if not lens_api_service.is_configured or not top_patent_numbers:
            return []

        logger.info(f"[PATENT API] Running citation expansion for top candidates: {top_patent_numbers[:3]}")
        citation_records = lens_api_service.fetch_citations_and_family(top_patent_numbers[:3])
        return citation_records or []


    def _fetch_from_patentsview(
        self,
        title: str,
        keywords: List[str],
        domain: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch supplementary patent records from USPTO PatentsView API."""
        import os
        if getattr(settings, "TESTING", False) or os.getenv("TESTING", "").lower() == "true":
            return []
        query_terms = [k for k in (keywords or []) if len(k) > 2]
        if not query_terms and title:
            query_terms = [w for w in title.split() if len(w) > 3][:3]
        if not query_terms:
            query_terms = [domain]

        search_query = " ".join(query_terms[:4])
        url = "https://api.patentsview.org/patents/query"
        results = []

        headers = {"User-Agent": "PatentLens-AI/1.0", "Accept": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        payload = {
            "q": {"_text_any": {"patent_title": search_query}},
            "f": ["patent_number", "patent_title", "patent_abstract", "patent_date"],
            "o": {"page": 1, "per_page": min(limit, 25)}
        }

        for attempt in range(3):
            try:
                with httpx.Client(timeout=10.0, follow_redirects=True) as http_client:
                    res = http_client.post(url, json=payload, headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        for p in data.get("patents") or []:
                            p_num = p.get("patent_number")
                            if p_num:
                                results.append({
                                    "patent_number": f"US-{p_num}",
                                    "title": p.get("patent_title") or "Untitled US Patent",
                                    "abstract": p.get("patent_abstract") or f"Abstract for patent US-{p_num}.",
                                    "claims": "",
                                    "description": f"Patent disclosure for US-{p_num}. Abstract: {p.get('patent_abstract', '')}",
                                    "inventors": "USPTO Inventor",
                                    "assignee": "USPTO Assignee",
                                    "publication_date": p.get("patent_date") or "2023-01-01",
                                    "source_url": f"https://patents.google.com/patent/US{p_num}/en",
                                    "source_type": "USPTO",
                                    "document_type": "PATENT",
                                    "jurisdiction": "US"
                                })
                        break
                    elif res.status_code in [429, 503]:
                        time.sleep(1.5 * (attempt + 1))
            except Exception as e:
                logger.warning(f"PatentsView API attempt {attempt + 1} failed: {e}")
                time.sleep(1.0)

        return results

    def _fetch_from_arxiv(
        self,
        title: str,
        keywords: List[str],
        domain: str,
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Fetch Non-Patent Literature records from arXiv API.
        STRICT REQUIREMENT: Source must be labeled 'arXiv' and Document Type 'NON-PATENT LITERATURE'.
        """
        import os
        if getattr(settings, "TESTING", False) or os.getenv("TESTING", "").lower() == "true":
            return []
        import xml.etree.ElementTree as ET
        import urllib.parse

        clean_keywords = []
        for k in (keywords or []):
            words = [w.strip() for w in k.split() if len(w.strip()) > 2]
            clean_keywords.extend(words)
        if not clean_keywords and title:
            clean_keywords = [w.strip() for w in title.split() if len(w.strip()) > 3]
        if not clean_keywords:
            clean_keywords = [domain or "technology"]

        target_terms = [urllib.parse.quote(t) for t in clean_keywords[:3] if t]
        search_param = "+OR+".join([f"all:{t}" for t in target_terms]) if target_terms else "all:irrigation"
        url_arxiv = f"https://export.arxiv.org/api/query?search_query={search_param}&start=0&max_results={limit}&sortBy=relevance&sortOrder=descending"

        records = []
        try:
            arxiv_headers = {
                "User-Agent": "PatentLens-AI/1.0 (mailto:inventor@startup.com)",
                "Accept": "application/atom+xml, application/xml, text/xml, */*"
            }
            with httpx.Client(timeout=4.0, follow_redirects=True) as http_client:
                res = http_client.get(url_arxiv, headers=arxiv_headers)
                if res.status_code == 200:
                    root = ET.fromstring(res.text)
                    namespace = {'atom': 'http://www.w3.org/2005/Atom'}

                    for idx, entry in enumerate(root.findall('atom:entry', namespace)):
                        id_elem = entry.find('atom:id', namespace)
                        raw_id = (id_elem.text or "").split('/')[-1] if (id_elem is not None and id_elem.text) else f"DOC-{idx}"
                        doc_id = raw_id.replace('.', '-').replace('/', '-')
                        
                        # Format clearly as arXiv non-patent literature identifier
                        doc_number = f"ARXIV-{doc_id.upper()}"

                        t_elem = entry.find('atom:title', namespace)
                        p_title = (t_elem.text or "").replace('\n', ' ').strip() if (t_elem is not None and t_elem.text) else "arXiv Research Paper"

                        s_elem = entry.find('atom:summary', namespace)
                        p_summary = (s_elem.text or "").replace('\n', ' ').strip() if (s_elem is not None and s_elem.text) else ""

                        pub_elem = entry.find('atom:published', namespace)
                        p_date = (pub_elem.text or "")[:10] if (pub_elem is not None and pub_elem.text) else "2024-01-01"

                        # Extract authors
                        authors: List[str] = []
                        for a in entry.findall('atom:author', namespace):
                            name_elem = a.find('atom:name', namespace)
                            if name_elem is not None and name_elem.text:
                                authors.append(name_elem.text.strip())
                        author_str = ", ".join(authors[:3]) if authors else "arXiv Researcher"

                        records.append({
                            "patent_number": doc_number,
                            "title": p_title,
                            "abstract": p_summary,
                            "claims": "",
                            "description": f"Scientific paper disclosure for '{p_title}'. Abstract: {p_summary}",
                            "inventors": author_str,
                            "assignee": "arXiv Open Science Repository",
                            "publication_date": p_date,
                            "source_url": f"https://arxiv.org/abs/{raw_id}",
                            "source_type": "arXiv",
                            "document_type": "NON-PATENT LITERATURE",
                            "jurisdiction": "GLOBAL"
                        })
        except Exception as e:
            logger.warning(f"Error fetching from arXiv API: {e}")

        return records


patent_api_service = PatentAPIService()
