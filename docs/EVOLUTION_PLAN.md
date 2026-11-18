# EnterpriseIQ Phase 0: Evolution Plan

## Architecture direction

EnterpriseIQ should evolve as a modular monolith. Existing LangGraph, FastAPI, Qdrant, FlashRank, Groq, Gemini, and Streamlit capabilities will remain; PostgreSQL and React will be introduced only after stable domain boundaries exist.

```text
FastAPI / Streamlit compatibility layer
  -> typed API schemas
  -> investigation application services
  -> LangGraph investigation workflow
       -> intake
       -> plan
       -> retrieval
       -> analysis
       -> tools
       -> verification
       -> report
       -> approval interrupt
  -> PostgreSQL repositories / persistent checkpointer
  -> Qdrant dense search
  -> BM25 lexical index
  -> FlashRank reranker
  -> typed read-only tools
```

Keep retrieval, document parsing, chunking, embedding, vector persistence, domain persistence, and report generation as separate responsibilities.

## Target module boundaries

```text
app/
  api/
  core/
  domain/
  ingestion/
  retrieval/
  agents/
  tools/
  investigations/
  evidence/
  persistence/
  services/
ui/
frontend/        # added progressively during the React phase
tests/
  unit/
  integration/
  evaluation/
evals/
docs/
infra/
```

These folders are target boundaries, not an instruction to move every working module in one pass.

## Target domain models

Add Pydantic models for at least:

- Investigation
- InvestigationStatus
- InvestigationPlan
- InvestigationTask
- EvidenceReference
- RetrievedEvidence
- Hypothesis
- Finding
- FindingClassification
- UnresolvedQuestion
- ToolExecution
- ApprovalRequest
- ApprovalDecision
- InvestigationReport
- ExecutionMetadata

Finding classifications must be `confirmed`, `probable`, `possible`, `unverified`, or `contradicted`.

## Proposed implementation phases

### Phase 1: Stabilize the foundation

Deliverables:

- Pydantic settings
- Consistent package/test configuration
- FastAPI health and typed error responses
- Explicit provider interfaces
- Refactored state and node typing
- Regression tests around current query behavior

Acceptance:

- Existing page tests pass in a documented standard command
- Existing RAG flow remains query-compatible
- External failures are explicit and testable

### Phase 2: Hybrid retrieval and provenance

Deliverables:

- BM25 index
- Dense/sparse fusion
- Metadata filters and relevance thresholds
- Source-aware evidence records
- Incremental ingestion primitives
- Retrieval evaluation scaffold

Acceptance:

- Every retrieved result includes source and chunk identity
- Dense-only and hybrid modes can be evaluated from the same fixed dataset

### Phase 3: PostgreSQL and domain persistence

Deliverables:

- SQLAlchemy/Alembic setup
- Organizations, users, investigations, evidence, tool records, approvals, and audit events
- Migrations and indexes
- Repository interfaces

Acceptance:

- CRUD and investigation transitions are covered by integration tests
- All tenant-scoped queries enforce organization boundaries

### Phase 4: Multi-agent investigation workflow

Deliverables:

- Intake, planning, retrieval, analysis, and reporting nodes
- Conditional routing
- Maximum steps and bounded retries
- Durable LangGraph checkpoints

Acceptance:

- Investigations can be started, paused, resumed, and completed
- Repeated graph execution is bounded and deterministic where provider nondeterminism is excluded

### Phase 5: Safe tools

Deliverables:

- Typed tool registry
- Knowledge, incident, record, deployment, log, monitoring, and timestamp tools
- Read-only defaults
- Permission checks and structured outputs
- Simulated integrations

Acceptance:

- Invalid inputs are rejected before execution
- Tool failures are recorded without fabricating results

### Phase 6: Verification and reporting

Deliverables:

- Evidence-to-finding correlation
- Unsupported citation checks
- Contradiction detection
- Investigation report model and renderer

Acceptance:

- Material findings require supported evidence references
- Unsupported/contradictory findings are not promoted to confirmed

### Phase 7: Human approvals

Deliverables:

- LangGraph interrupts
- Approval API
- Durable approval decisions
- Resumed workflow behavior

Acceptance:

- Sensitive operations cannot execute before approval
- Rejection and restart paths are auditable

### Phase 8: Evaluation and observability

Deliverables:

- Labelled incident benchmark
- Retrieval metrics
- Generation metrics
- Agent metrics
- Latency/token/cost metrics
- Structured tracing and audit logging
- Prompt-injection tests

Acceptance:

- Metrics come only from actual benchmark execution
- Baseline, hybrid RAG, and EnterpriseIQ workflows use one reproducible harness

### Phase 9: React dashboard

Deliverables:

- React/TypeScript API client
- Dashboard and investigation pages
- Evidence, tool, approval, and history views

Acceptance:

- Core investigation lifecycle works without using Streamlit
- Streamlit compatibility is retained during migration

### Phase 10: Deployment

Deliverables:

- Docker and compose setup
- Migration execution
- Health/readiness endpoints
- Test and deployment documentation

Acceptance:

- Clean environment setup and smoke test pass
- No provider credentials are committed

## Priority sequence

1. Stabilize and test the existing RAG behavior.
2. Introduce evidence and provenance types with hybrid retrieval.
3. Persist investigation domain state.
4. Add investigation nodes and tools.
5. Add verification and approvals.
6. Build evaluation and observability.
7. Migrate the frontend.
8. Add deployment infrastructure.

## Implementation status

The follow-up request authorized implementation beyond Phase 0. A local-first vertical slice now covers the investigation lifecycle, document upload, BM25/optional tenant-filtered Qdrant retrieval, durable SQLite/PostgreSQL persistence and graph checkpoints, simulated read-only tools, evidence/citation checks, narrow status-conflict detection, approval records, React UI, benchmark scaffolding, Alembic migrations, and Docker Compose.

This does not mean every enterprise target in Phases 1–10 is production-complete. Real operational integrations, multi-user authentication/RBAC, broad semantic verification, live external-provider benchmark results, and production-scale testing remain follow-up work. Continue in small, reviewed increments rather than treating this vertical slice as approval to execute operational changes.
