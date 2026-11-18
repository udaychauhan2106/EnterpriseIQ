# EnterpriseIQ Phase 0: Baseline Architecture

This is the repository snapshot recorded before the implementation work requested after Phase 0. The current EnterpriseIQ vertical slice is documented in the README and in the implementation notes at the end of this file.

## Repository state

- Branch: `feature/enterpriseiq`
- Working tree: clean at audit time
- Python: 3.12+
- Package/project management: `uv`
- Current project name: `rag-project`
- Primary application: FastAPI plus Streamlit
- Existing tests: `tests/pages/test_validators.py` and `tests/pages/test_normalizer.py`

## Runtime architecture

```text
Streamlit UI
  -> POST /query
  -> FastAPI app.main
  -> LangGraph rag_agent
       -> planner
       -> retriever [conditional]
       -> responder
  -> Groq
  -> Gemini embeddings or Sentence Transformers fallback
  -> Qdrant
  -> FlashRank
```

Document ingestion is a separate command-line pipeline:

```text
DATA/<source-type>/<files>
  -> format parser
  -> paragraph chunker
  -> embedding provider
  -> Qdrant points
  -> processed_data/<source-type>/<filename>.json
  -> processed_data/failed_files.json
```

## Main modules

### API

- `app/main.py`
  - FastAPI application
  - `POST /query`
  - `GET /graph`
  - `GET /`
  - Wraps LangGraph invocation and provider failures

### Configuration

- `app/config.py`
  - Environment loading through `python-dotenv`
  - Groq, Gemini, Qdrant, and LiveRAG settings
  - Class-based settings rather than a Pydantic settings model

### LangGraph orchestration

- `app/agents/graph.py`
  - Defines one three-node `StateGraph`
  - Uses `MemorySaver`
  - Routes conversational and technical questions
- `app/agents/state.py`
  - `TypedDict` state for messages, query, documents, plan, status, and final answer
- `app/agents/nodes/planner.py`
  - Classifies conversational versus technical queries
  - Rewrites technical search queries using Groq
- `app/agents/nodes/retriever.py`
  - Performs dense Qdrant search
  - Reranks document text with FlashRank
- `app/agents/nodes/responder.py`
  - Builds an LLM prompt from history and retrieved context
  - Generates the final answer

### Ingestion

- `app/ingestion/processor.py`
  - Recursive file discovery
  - Parser dispatch
  - Collection creation and dimension validation
  - Batched Qdrant upserts
  - Local processed JSON
  - Failed-file tracking and retry CLI
- `app/ingestion/loaders/`
  - PDF: pypdf with pdfplumber fallback
  - HTML: BeautifulSoup
  - TXT: UTF-8 text
  - DOCX/PPTX: Unstructured partitioning
- `app/ingestion/chunking/splitter.py`
  - Paragraph-based fixed-size chunking

### Retrieval services

- `app/services/retrieval/embeddings.py`
  - Gemini embeddings with Sentence Transformers fallback
  - Gemini rate-limit and quota handling
- `app/services/retrieval/qdrant_service.py`
  - Dense vector search against the `enterprise_rag` collection
- `app/services/retrieval/ranking_service.py`
  - Local FlashRank reranking

### Streamlit

- `ui/app.py`
  - Chat interface
  - Thread-scoped session ID
  - Displays thought/process steps and retrieved context
  - Calls FastAPI synchronously

### LiveRAG page ingestion support

- `app/pages/schemas.py`
  - Strict Pydantic 2 request and response models
- `app/pages/validators.py`
  - URL, text size, block count, and timestamp validation
- `app/pages/normalizer.py`
  - NFC normalization, block rendering, SHA-256 hash, and word count
- `app/pages/router.py`
  - Placeholder
- `app/pages/service.py`
  - Placeholder

## Module dependency map

```text
app.main
  -> app.agents.graph
       -> app.agents.state
       -> app.agents.nodes.planner
       -> app.agents.nodes.retriever
            -> app.services.retrieval.qdrant_service
                 -> app.services.retrieval.embeddings
                 -> app.config
            -> app.services.retrieval.ranking_service
       -> app.agents.nodes.responder

app.ingestion.processor
  -> app.config
  -> app.ingestion.loaders.*
  -> app.ingestion.chunking.splitter
  -> app.services.retrieval.embeddings
  -> Qdrant

ui.app
  -> app.main / POST /query

app.pages.normalizer
  -> app.pages.schemas
  -> app.pages.validators

app.pages.validators
  -> app.config
  -> app.pages.schemas
```

## Data responsibilities

- `DATA/`: source documents
- `processed_data/`: extracted chunks and failed-file report
- Qdrant: chunk vectors and payload metadata
- LangGraph `MemorySaver`: process-local conversation state
- Streamlit session state: UI messages and thread ID

## Actual repository structure

```text
app/
  __init__.py
  config.py
  main.py
  agents/
  ingestion/
  pages/
  services/
tests/
  pages/
ui/
DATA/
processed_data/
eval/
docs/ (to be added incrementally)
pyproject.toml
uv.lock
README.md
test_groq.py
```

`eval/` exists but contains no Python benchmark implementation. `processed_data/` contains generated artifacts.

## Baseline validation

- `uv run pytest -q tests/pages` failed by default because repository-root imports were not on `PYTHONPATH`.
- `PYTHONPATH=. uv run pytest -q tests/pages`: 25 tests passed.
- `uv run pytest -q` also attempted to collect `test_groq.py`, where the direct `groq` package is not currently a declared dependency.

These baseline results do not exercise external LLM, Gemini, Qdrant, ingestion, or FastAPI integration behavior.

## Current EnterpriseIQ vertical slice

The implementation adds typed investigation models, SQLAlchemy persistence, Alembic migrations, SQLite/PostgreSQL support, and LangGraph SQLite/PostgreSQL checkpoint savers. The investigation graph has intake, retrieval, read-only tool, analysis, verification, and reporting nodes. Workflow state and events are persisted after each node and queued/running investigations are replayed at application startup.

FastAPI exposes versioned knowledge upload/search/status, investigation lifecycle/history/report/events, approval, authentication-status, and health routes. Uploads are size/type checked, content-hash deduplicated, chunked, and versioned by source name. Retrieval uses BM25 locally; Qdrant dense fusion is optional, tenant-filtered, and disabled by default.

The React/TypeScript UI is in `frontend/`; FastAPI serves its production build when present. `docker-compose.yml` runs the API, PostgreSQL, and Qdrant. The evaluation harness and synthetic labelled set are in `evals/`.

This implementation intentionally does not ship live operations connectors, interactive user authentication/RBAC, mutating tools, or a semantic model for general contradiction detection. Simulated tools report `not_configured`; no root cause is asserted from retrieval alone.
