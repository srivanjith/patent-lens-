import re
from typing import Optional, List, Dict, Any

def clean_text(text: str) -> str:
    """Clean and normalize raw text while preserving technical terminology."""
    if not text:
        return ""
    # Normalize multiple whitespace, tabs, and newlines
    normalized = re.sub(r'\s+', ' ', text).strip()
    return normalized

def validate_invention_input(title: str, description: str, min_desc_length: int = 20) -> dict:
    """Validate invention input parameters."""
    cleaned_title = clean_text(title)
    cleaned_desc = clean_text(description)
    
    if not cleaned_title:
        return {"valid": False, "error": "Invention title cannot be empty."}
    if len(cleaned_desc) < min_desc_length:
        return {
            "valid": False,
            "error": f"Invention description must be at least {min_desc_length} characters long for accurate AI processing."
        }
        
    return {"valid": True, "title": cleaned_title, "description": cleaned_desc}

def prepare_combined_text(title: str, problem_statement: str, description: str, keywords: Optional[List[str]] = None) -> str:
    """
    Combine invention fields into a rich semantic string for SBERT embedding generation.
    Preserves all domain-specific terminology.
    """
    parts = []
    if title:
        parts.append(f"Title: {clean_text(title)}")
    if problem_statement:
        parts.append(f"Problem Solved: {clean_text(problem_statement)}")
    if description:
        parts.append(f"Technical Description: {clean_text(description)}")
    if keywords and isinstance(keywords, list):
        kw_str = ", ".join([clean_text(k) for k in keywords if k])
        if kw_str:
            parts.append(f"Keywords: {kw_str}")
            
    return " | ".join(parts)

def chunk_text_intelligently(text: str, max_words: int = 400) -> str:
    """Intelligently truncate or chunk long specifications to preserve core technical disclosures."""
    cleaned = clean_text(text)
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned
    return " ".join(words[:max_words]) + "..."

def prepare_weighted_patent_text(
    title: str,
    abstract: str,
    claims: str = "",
    description: str = "",
    max_desc_words: int = 300
) -> str:
    """
    Construct weighted text representation prioritizing:
    1. Claims (Highest Priority)
    2. Abstract (High Priority)
    3. Description (Medium-High Priority - truncated/chunked)
    4. Title (Medium Priority)
    """
    c_title = clean_text(title)
    c_abstract = clean_text(abstract)
    c_claims = clean_text(claims)
    c_desc = chunk_text_intelligently(description, max_words=max_desc_words)

    parts = []
    if c_claims:
        # Repeat claims twice to boost weight in SBERT embedding vector representation
        parts.append(f"CLAIMS: {c_claims}")
        parts.append(f"INDEPENDENT CLAIMS: {c_claims[:600]}")
    if c_abstract:
        parts.append(f"ABSTRACT: {c_abstract}")
    if c_desc:
        parts.append(f"SPECIFICATION SUMMARY: {c_desc}")
    if c_title:
        parts.append(f"TITLE: {c_title}")

    return " | ".join(parts)

