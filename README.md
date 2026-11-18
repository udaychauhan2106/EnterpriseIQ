# EnterpriseIQ

## Agentic Enterprise Knowledge & Incident Investigation Platform

EnterpriseIQ evolves the existing AgenticRAG repository into a modular incident-investigation platform. The existing conversational RAG endpoint and ingestion pipeline remain available; the new investigation workflow runs locally with evidence provenance, durable state, and explicitly simulated operational tools.

## Incident investigation quick start

```powershell
Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

In another terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The local investigation workflow uses SQLite, BM25 over existing `processed_data/` chunks, and uploaded files; it requires no provider credentials. Qdrant dense retrieval is opt-in via `ENTERPRISEIQ_ENABLE_EXTERNAL_RETRIEVAL=true`. Provider-backed features must be configured deliberately and should not receive sensitive content without authorization.

The default mock deployment, incident, logs, and health tools make no external calls and return `not_configured`; reports state that no live operational data was queried. The workflow never performs remediation. A single environment API key can be enabled with `ENTERPRISEIQ_API_KEY`; in production it is mandatory and scoped to `ENTERPRISEIQ_ORGANIZATION_ID`. Development organization headers are not authentication.

### Investigation API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Database health |
| `POST` | `/api/v1/knowledge/documents` | Validate, parse, deduplicate, version, and index a document |
| `GET` | `/api/v1/knowledge/documents/{id}` | Check ingestion status |
| `GET` | `/api/v1/knowledge/search?q=...` | Search with BM25 and optional tenant-filtered dense fusion |
| `POST` | `/api/v1/investigations` | Start an investigation |
| `GET` | `/api/v1/investigations` | Investigation history |
| `GET` | `/api/v1/investigations/{id}` | Plan, evidence, tool history, and status |
| `GET` | `/api/v1/investigations/{id}/events/stream` | Server-sent workflow updates |
| `GET` | `/api/v1/investigations/{id}/report` | Evidence-backed report |
| `POST` | `/api/v1/investigations/{id}/approvals` | Request human approval |
| `GET` | `/api/v1/approvals` | Pending approval queue |
| `POST` | `/api/v1/approvals/{id}/decision` | Record approval or rejection |

Uploaded files are limited to 10 MiB; DOCX/PPTX archive contents are limited to 50 MiB expanded by default. Supported formats: PDF, DOCX, PPTX, TXT, Markdown, HTML, CSV, JSON, and log files. SQLite is the local default; set `DATABASE_URL` to a `postgresql+psycopg://...` URL to use PostgreSQL. `APP_ENV=production` applies Alembic migrations during startup and requires an API key.

### Tests and evaluation

```powershell
uv run pytest -q
uv run alembic upgrade head
```

The labelled evaluation set in `evals/datasets/incident_benchmark.json` is synthetic. The retrieval benchmark compares local dense semantic search and BM25+dense fusion without downloading a model or contacting a model provider:

```powershell
uv run python -m evals.run_benchmark
```

The default `all-mpnet-base-v2` model must already be cached locally. Results are written to `evals/reports/latest.json` only after a real run; this repository does not claim benchmark scores.

### Docker

Set `POSTGRES_PASSWORD`, `DATABASE_URL` (URL-encode special characters in credentials), and `ENTERPRISEIQ_API_KEY` in `.env`, then run:

```powershell
docker compose up --build
```

The compose stack binds the API and Qdrant to localhost and persists PostgreSQL/Qdrant data in Docker volumes.

## Existing conversational RAG

The original `/query` chat path is retained for compatibility. It uses LangGraph, Qdrant, FlashRank, Groq, and Gemini/Sentence Transformers, and is described below. It is separate from the offline-first incident-investigation workflow.

---

## Overview

Traditional RAG pipelines generally follow a fixed flow:

```text
User Query → Retrieve Documents → Generate Answer
```

This project introduces a stateful orchestration layer using LangGraph:

```text
                         ┌─────────────────────┐
                         │      User Query     │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │     Planner Node    │
                         │                     │
                         │ Classify Query and  │
                         │ Rewrite Search Query│
                         └──────────┬──────────┘
                                    │
                                    ▼
                           Conditional Routing
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                         ▼                     ▼
                Conversational Query     Retrieval Required
                         │                     │
                         │                     ▼
                         │            ┌──────────────────┐
                         │            │ Semantic Search  │
                         │            │     Qdrant       │
                         │            └────────┬─────────┘
                         │                     │
                         │                     ▼
                         │            ┌──────────────────┐
                         │            │    FlashRank     │
                         │            │    Reranking     │
                         │            └────────┬─────────┘
                         │                     │
                         └───────────┬─────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │    Responder Node   │
                          │                     │
                          │ Context + History + │
                          │   Response Generation│
                          └──────────┬──────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │     Final Answer    │
                          └─────────────────────┘
```

The planner determines whether a query requires knowledge-base retrieval or can be answered directly using conversation history.

Technical queries are rewritten into retrieval-friendly search queries, embedded, searched against Qdrant, reranked using FlashRank, and passed to the responder for grounded answer generation.

---

## Features

* Document ingestion pipeline
* Recursive directory processing
* Multi-format document parsing
* Configurable text chunking
* Embedding generation
* Vector storage using Qdrant
* Semantic similarity search
* FlashRank-based document reranking
* Conversation-aware query planning
* Retrieval query rewriting
* Conditional routing using LangGraph
* Stateful conversation history using LangGraph checkpointing
* Context-aware response generation
* FastAPI backend
* Streamlit user interface
* Source document display
* Retrieval and pipeline execution status

---

## Tech Stack

| Component           | Technology                                       |
| ------------------- | ------------------------------------------------ |
| Language            | Python                                           |
| Agent Orchestration | LangGraph                                        |
| LLM Framework       | LangChain                                        |
| LLM Provider        | Groq                                             |
| Embeddings          | Google Gemini Embeddings / Sentence Transformers |
| Vector Database     | Qdrant                                           |
| Reranking           | FlashRank                                        |
| Backend API         | FastAPI                                          |
| Frontend            | React / TypeScript (new UI), Streamlit (legacy)  |
| Configuration       | Environment variables (`.env`)                  |
| Package Management  | uv                                               |

---

## Legacy RAG Run Locally

The legacy chat endpoint requires provider settings. Start the API and Streamlit UI:

```powershell
Copy-Item .env.example .env
uv sync
```

```powershell
uv run uvicorn app.main:app --reload
```

```powershell
uv run streamlit run ui/app.py
```

---

## LiveRAG Validation Configuration

The LiveRAG page-validation layer reads these limits from environment variables:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `LIVERAG_MAX_EXTRACTED_TEXT_BYTES` | `512000` | Maximum UTF-8 bytes in the request's full text and, independently, in its structured blocks (500 KiB). |
| `LIVERAG_MAX_CONTENT_BLOCKS` | `1000` | Maximum number of structured content blocks. |
| `LIVERAG_EXTRACTION_MAX_FUTURE_SKEW_SECONDS` | `300` | Allowed future clock skew for the client extraction timestamp (5 minutes). |
| `LIVERAG_EXTRACTION_MAX_AGE_DAYS` | `30` | Maximum age allowed for the client extraction timestamp. |

These are extraction-text limits, not HTTP request-body limits. The client word
count is treated as untrusted metadata; the backend calculates its own count
from normalized block content.

---

## Project Structure

```text
app/
  agents/              # Existing chat graph and responder
  api/                 # Investigation and knowledge-base routes
  domain/              # Pydantic investigation/evidence contracts
  ingestion/           # Existing parsers and ingestion pipeline
  investigations/      # LangGraph workflow and durable orchestration
  pages/               # LiveRAG schemas and validation
  persistence/         # SQLAlchemy models, migrations, graph checkpoints
  retrieval/           # BM25 and optional Qdrant hybrid search
  services/retrieval/  # Existing Qdrant, embeddings, FlashRank services
frontend/              # React/TypeScript application
evals/                 # Synthetic labelled data and metric runners
migrations/            # Alembic database schema history
tests/                 # API, workflow, evaluation, and page tests
ui/                    # Retained Streamlit compatibility interface
```

---

# System Architecture

The application consists of two independent pipelines:

1. Document ingestion pipeline
2. Query-time RAG pipeline

---

## 1. Document Ingestion Pipeline

The ingestion pipeline processes documents and stores their vector representations in Qdrant.

```text
Documents
    │
    ▼
File Discovery
    │
    ▼
Document Parser
    │
    ▼
Extracted Text
    │
    ▼
Text Chunking
    │
    ▼
Embedding Generation
    │
    ▼
Vectors + Metadata
    │
    ▼
Qdrant Vector Database
```

### Processing Steps

#### File Discovery

The ingestion pipeline recursively scans the configured data directory for supported documents.

#### Document Parsing

Files are processed using format-specific parsers to extract textual content and metadata.

#### Text Chunking

Extracted documents are divided into smaller chunks suitable for semantic retrieval and LLM context construction.

#### Embedding Generation

Each chunk is converted into a dense vector representation using the configured embedding model.

#### Vector Storage

The embeddings are stored in Qdrant together with metadata such as source information and chunk content.

---

## 2. Query-Time RAG Pipeline

User queries are processed through a LangGraph state machine.

```text
START
  │
  ▼
Planner
  │
  ▼
Conditional Router
  │
  ├──────── Conversational Query ─────────────┐
  │                                           │
  ▼                                           │
Retriever                                     │
  │                                           │
  ▼                                           │
Query Embedding                               │
  │                                           │
  ▼                                           │
Qdrant Vector Search                          │
  │                                           │
  ▼                                           │
FlashRank Reranking                           │
  │                                           │
  ▼                                           │
Retrieved Context                             │
  │                                           │
  └───────────────────┬───────────────────────┘
                      │
                      ▼
                   Responder
                      │
                      ▼
                 Final Answer
                      │
                      ▼
                     END
```

---

## LangGraph State

Application state is shared between nodes during graph execution.

The state contains information such as:

```text
messages

current_query

documents

plan

status

final_answer
```

Each LangGraph node receives the current state and returns partial state updates.

LangGraph merges those updates before executing the next node.

Conversation messages use an additive reducer so new messages are appended to the existing conversation history.

---

## Planner Node

The planner is the first node executed for every user request.

Responsibilities:

* Analyze the current user query
* Inspect conversation history
* Determine whether retrieval is necessary
* Rewrite technical questions into retrieval-friendly search queries
* Route conversational queries directly to response generation

Example:

```text
User Query

"Can you explain how checkpointing works in LangGraph?"
```

Planner output:

```text
LangGraph checkpointing and conversation persistence
```

The rewritten query is then passed to the retrieval pipeline.

For conversational messages such as:

```text
Hello!
```

the planner marks the query as conversational and skips document retrieval.

---

## Retrieval Pipeline

The retrieval node performs a two-stage retrieval process.

### Stage 1: Semantic Vector Search

The rewritten query is converted into an embedding.

```text
Search Query
      │
      ▼
Embedding Model
      │
      ▼
Query Vector
      │
      ▼
Qdrant
      │
      ▼
Top-K Candidate Documents
```

Qdrant retrieves semantically similar chunks from the vector database.

### Stage 2: Document Reranking

The retrieved candidates are passed to FlashRank.

```text
Query
  +
Candidate Documents
        │
        ▼
    FlashRank
        │
        ▼
Relevance Scores
        │
        ▼
Top Ranked Documents
```

Reranking improves the ordering of retrieved documents before they are passed to the language model.

---

## Responder Node

The responder generates the final answer.

For retrieval-based queries, the prompt contains:

```text
Retrieved Context

+

Conversation History

+

User Question
```

For conversational queries, the responder uses conversation history without performing vector retrieval.

The generated assistant response is appended to the LangGraph message history and stored in the final graph state.

---

## Conversation Memory

The application uses LangGraph checkpointing with a thread identifier.

```text
thread_id
    │
    ▼
LangGraph Checkpointer
    │
    ▼
Conversation State
```

Requests using the same `thread_id` can continue the same conversation.

Requests using different thread identifiers maintain independent conversation state.

The legacy `/query` chat uses an in-memory checkpointer and loses chat state on process restart. Incident investigations use a persistent SQLite/PostgreSQL LangGraph checkpointer plus database snapshots and can be replayed after interruption.

---

# API

The backend is implemented using FastAPI.

## Query Endpoint

```text
POST /query
```

### Example Request

```json
{
    "q": "Explain how transformers use self-attention.",
    "thread_id": "example-session-123"
}
```

### Example Response

```json
{
    "question": "Explain how transformers use self-attention.",
    "answer": "Self-attention allows each token in a sequence to...",
    "thought_process": [
        "Intent: Technical",
        "Search Term: transformer self-attention mechanism",
        "Context Retrieved"
    ],
    "status": "Response generated.",
    "sources": []
}
```

---

## Graph Visualization Endpoint

```text
GET /graph
```

Returns a Mermaid-generated visualization of the compiled LangGraph workflow.

---



# Example Query Flow

Consider the following user query:

```text
"How does self-attention work in transformers?"
```

### Step 1: FastAPI

The API receives:

```json
{
    "q": "How does self-attention work in transformers?",
    "thread_id": "session-123"
}
```

An initial LangGraph state is created.

### Step 2: Planner

The planner analyzes the conversation and generates a retrieval query:

```text
transformer self-attention mechanism
```

### Step 3: Routing

The conditional router detects that retrieval is required and sends execution to the retriever node.

### Step 4: Query Embedding

The retrieval query is converted into an embedding vector.

### Step 5: Vector Search

Qdrant retrieves the most semantically similar document chunks.

### Step 6: Reranking

FlashRank reranks the candidate documents according to their relevance to the query.

### Step 7: Response Generation

The responder receives:

```text
Top Ranked Documents

+

Conversation History

+

Original User Question
```

The LLM generates the final response.

### Step 8: State Update

The assistant response is appended to the conversation history.

### Step 9: API Response

FastAPI returns the generated answer, pipeline execution information, and retrieved sources to the client.

---

# Current Limitations

The investigation experience is a local-first vertical slice, not a fully integrated enterprise deployment:

* Deployment, log, monitoring, incident-history, and record tools are typed simulations. Live connectors are not included and return `not_configured`.
* The deterministic investigation analysis avoids unsupported LLM claims but is intentionally conservative; it does not replace a domain expert or establish causality.
* Contradiction detection is a narrow status-term heuristic. It is not a general semantic contradiction detector.
* The API key is a single deployment credential, not an interactive user identity, and organization scoping is not a substitute for production IAM/RBAC.
* The rate limiter is process-local; multi-worker deployments should enforce limits at a trusted gateway.
* Dense retrieval is optional and disabled by default. Existing Qdrant points without `organization_id` are excluded from tenant-filtered search until re-indexed.
* The benchmark data is synthetic, and dense benchmark execution requires the embedding model to be present in the local cache. No benchmark scores are asserted.
* The legacy `/query` chat still uses in-memory conversation checkpoints; durable investigation checkpoints are separate.
* PostgreSQL migrations and Docker Compose are provided, but production security, failover, backup, load, and recovery behavior still require deployment-specific verification.

---

# Future Improvements

Recommended next steps are real read-only integrations behind permissioned adapters, stronger identity and tenant authorization, semantic conflict verification, integration/load testing against PostgreSQL and Qdrant, operational observability, and a production CI/CD pipeline.

---

# Learning Objectives

This project was built to gain practical experience with:

* Designing end-to-end RAG applications
* Building document ingestion pipelines
* Working with vector databases
* Understanding semantic retrieval
* Implementing reranking pipelines
* Designing stateful AI workflows
* Using LangGraph for orchestration
* Building APIs around LLM applications
* Maintaining conversation state
* Connecting AI backends with user interfaces
