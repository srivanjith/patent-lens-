import sys
import os
import types
import logging
from contextlib import asynccontextmanager

# Add parent directory and backend directory to sys.path so imports work regardless of execution CWD
backend_dir = os.path.abspath(os.path.dirname(__file__))
parent_dir = os.path.abspath(os.path.join(backend_dir, ".."))

if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Ensure 'backend' module is registered so imports like 'from backend.app...' resolve in Vercel
try:
    import backend
except ModuleNotFoundError:
    backend_module = types.ModuleType("backend")
    backend_module.__path__ = [backend_dir]
    sys.modules["backend"] = backend_module

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base, ensure_columns_exist, init_mongo, close_mongo
from ml.embedding_service import embedding_service
from scripts.seed_database import seed_patents_if_needed

from app.api.auth import router as auth_router
from app.api.search import router as search_router
from app.api.patents import router as patents_router
from app.api.reports import router as reports_router
from app.api.users import router as users_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("patentlens.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for PatentLens AI Backend."""
    logger.info("Initializing PatentLens AI Backend...")
    logger.info("================ AI MODEL CONFIGURATION DIAGNOSTICS ================")
    logger.info(f"Gemini Model:    {settings.GEMINI_MODEL}")
    logger.info(f"Groq Model:      {settings.GROQ_MODEL}")
    logger.info(f"Embedding Model: {settings.MODEL_NAME}")
    logger.info("====================================================================")
    await init_mongo()
    yield
    await close_mongo()
    logger.info("Shutting down PatentLens AI Backend...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
    redirect_slashes=False
)

origins = [
    settings.FRONTEND_URL,
    "https://automated-patent-prior-art-search.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class VercelPathRewriteMiddleware:
    """
    ASGI Middleware to restore the original client URL path on Vercel.
    When Vercel rewrites requests to '/main.py', this middleware reads the original
    requested URI from 'x-forwarded-uri' or 'x-matched-path' headers so FastAPI router
    matches routes (/api/auth/login, /api/search, /docs, /) correctly.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if path in ["/main.py", "/main", "/api/index.py", "/api/index", "/index.py", "/index"] or path.startswith("/main.py/") or path.startswith("/api/index.py/"):
                headers = dict(scope.get("headers", []))
                forwarded_uri = headers.get(b"x-forwarded-uri", b"").decode("utf-8")
                if not forwarded_uri:
                    forwarded_uri = headers.get(b"x-matched-path", b"").decode("utf-8")
                if not forwarded_uri:
                    forwarded_uri = headers.get(b"x-invoke-path", b"").decode("utf-8")
                
                if forwarded_uri:
                    clean_path = forwarded_uri.split("?")[0]
                    scope["path"] = clean_path if clean_path else "/"
                else:
                    scope["path"] = "/"
        await self.app(scope, receive, send)

app.add_middleware(VercelPathRewriteMiddleware)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception on {request.url}: {exc}")
    origin = request.headers.get("origin") or "*"
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": str(exc) or "Internal server error occurred.",
            "error_code": "INTERNAL_SERVER_ERROR"
        }
    )
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

app.include_router(auth_router, prefix=settings.API_PREFIX)
app.include_router(search_router, prefix=settings.API_PREFIX)
app.include_router(patents_router, prefix=settings.API_PREFIX)
app.include_router(reports_router, prefix=settings.API_PREFIX)
app.include_router(users_router, prefix=settings.API_PREFIX)

@app.get("/")
@app.get("/api")
@app.get("/api/")
def health_check():
    return {
        "status": "OK",
        "service": "PatentLens AI Backend",
        "environment": settings.ENVIRONMENT,
        "backend_version": settings.VERSION,
        "scoring_engine_version": "2.0.0-deterministic-weighted",
        "deployment_revision": "2026-09-28-v2",
        "docs": "/docs"
    }

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)

if __name__ == "__main__":
    import uvicorn
    print("\n==================================================", flush=True)
    print("  Starting PatentLens AI Server on http://localhost:8000", flush=True)
    print("==================================================\n", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
