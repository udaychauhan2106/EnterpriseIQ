import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from alembic import command
from alembic.config import Config

from app.api.routes import router as enterprise_router
from app.config import PROJECT_ROOT, settings
from app.persistence.database import get_engine, initialize_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.APP_ENV.lower() == "production" and not settings.ENTERPRISEIQ_API_KEY:
        raise RuntimeError("ENTERPRISEIQ_API_KEY must be configured in production.")
    if settings.APP_ENV.lower() == "production":
        migration_config = Config(str(PROJECT_ROOT / "alembic.ini"))
        command.upgrade(migration_config, "head")
        initialize_database(create_schema=False)
    else:
        initialize_database()
    from app.investigations.service import resume_interrupted_investigations

    resume_interrupted_investigations()
    yield


app = FastAPI(title="EnterpriseIQ Incident Investigation API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.ENTERPRISEIQ_CORS_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(enterprise_router)
_frontend_assets = PROJECT_ROOT / "frontend" / "dist" / "assets"
if _frontend_assets.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=_frontend_assets), name="frontend-assets")

_PUBLIC_PATHS = {"/", "/health", "/openapi.json", "/docs", "/redoc"}
_RATE_LOCK = threading.Lock()
_REQUEST_TIMES: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def api_key_guard(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    client_host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _RATE_LOCK:
        timestamps = _REQUEST_TIMES[client_host]
        while timestamps and now - timestamps[0] >= 60:
            timestamps.popleft()
        if len(timestamps) >= settings.ENTERPRISEIQ_RATE_LIMIT_PER_MINUTE:
            return Response(
                content='{"detail":"Rate limit exceeded."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )
        timestamps.append(now)
        if len(_REQUEST_TIMES) > 10_000:
            expired = [
                host
                for host, requests in _REQUEST_TIMES.items()
                if not requests or now - requests[-1] >= 60
            ]
            for host in expired:
                _REQUEST_TIMES.pop(host, None)
    required_key = settings.ENTERPRISEIQ_API_KEY
    if (
        required_key
        and request.url.path not in _PUBLIC_PATHS
        and not request.url.path.startswith("/assets/")
    ):
        supplied = request.headers.get("x-api-key", "")
        authorization = request.headers.get("authorization", "")
        if not supplied and authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
        if not secrets.compare_digest(supplied, required_key):
            return Response(
                content='{"detail":"Invalid or missing API key."}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


class QueryRequest(BaseModel):
    q: str = Field(min_length=1, max_length=10_000)
    thread_id: str | None = "default_user"


@app.get("/")
def home():
    frontend_index = PROJECT_ROOT / "frontend" / "dist" / "index.html"
    if frontend_index.is_file():
        return FileResponse(frontend_index)
    return {
        "message": "EnterpriseIQ Incident Investigation API is live.",
        "frontend": "Run `cd frontend && npm install && npm run dev` for the development UI.",
    }


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    return {"status": "ok", "database": "ok"}


@app.get("/graph")
def get_graph_image():
    try:
        from app.agents.graph import rag_agent

        png_bytes = rag_agent.get_graph().draw_mermaid_png()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as exc:
        logger.exception("Could not render legacy RAG graph")
        raise HTTPException(status_code=503, detail="Could not render the RAG workflow graph.") from exc


@app.post("/query")
def query(
    request: QueryRequest,
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-Id")] = None,
):
    del x_organization_id
    if len(request.q) > settings.ENTERPRISEIQ_MAX_QUERY_CHARS:
        raise HTTPException(
            status_code=413,
            detail="Query exceeds the configured character limit.",
        )
    try:
        from app.agents.graph import rag_agent

        initial_state = {
            "messages": [{"role": "user", "content": request.q}],
            "current_query": request.q,
            "documents": [],
            "plan": ["Start"],
            "status": "Initializing Graph...",
        }
        config = {"configurable": {"thread_id": request.thread_id or "default_user"}}
        final_output = rag_agent.invoke(initial_state, config=config)
        return {
            "question": request.q,
            "answer": final_output.get("final_answer"),
            "thought_process": final_output.get("plan"),
            "status": final_output.get("status"),
            "sources": final_output.get("documents", []),
        }
    except Exception as exc:
        logger.exception("Legacy RAG query failed")
        raise HTTPException(
            status_code=502,
            detail="The AI backend could not process the request. Check backend logs for details.",
        ) from exc
