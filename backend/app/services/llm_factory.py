from typing_extensions import Optional
import logging
from typing import Union, Optional
from app.core.config import settings
from app.services.gemini_service import GeminiService
from app.services.groq_service import GroqService
logger = logging.getLogger("patentlens.llm_factory")

def get_llm_service(provider_override: Optional[str] = None) -> Union[GeminiService, GroqService]:
    """
    Factory function returning the configured LLM service (GeminiService or GroqService).
    Checks provider_override first, then settings.LLM_PROVIDER (defaults to 'gemini').
    """
    provider = (provider_override or getattr(settings, "LLM_PROVIDER", "gemini")).strip().lower()
    
    if provider == "groq":
        logger.info("Initializing Groq LLM Service provider.")
        return GroqService()
    else:
        logger.info(f"Initializing Gemini LLM Service provider ({getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')}).")
        return GeminiService()