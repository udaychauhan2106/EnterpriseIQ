# EnterpriseIQ Phase 0: Baseline Gap Analysis

This gap list was captured before the post-Phase-0 implementation request. See `CURRENT_ARCHITECTURE.md` for the code now added and the remaining product limitations.

## Current reusable components

### Reuse largely unchanged

- FastAPI application shell and `/query` endpoint pattern
- LangGraph `StateGraph` orchestration pattern
- Existing planner, retriever, and responder node separation
- Qdrant query and collection setup
- FlashRank reranking service
- PDF, HTML, TXT, DOCX, and PPTX parsers
- Recursive ingestion and failed-file retry behavior
- Gemini embedding fallback to Sentence Transformers
- Streamlit chat as an interim frontend
- Strict Pydantic page models and deterministic page normalization
- Existing unit tests for page validation and normalization

### Reuse after refactoring

- `AgentState`: convert from a minimal `TypedDict` into versioned Pydantic investigation state
- `MemorySaver`: replace for durable deployments or add a PostgreSQL checkpointer implementation
- Qdrant service: preserve dense retrieval, add payload metadata and result provenance
- Ranking service: preserve FlashRank as the reranker and return score-bearing results
- Embedding service: introduce explicit provider selection and collection compatibility checks
- Ingestion processor: split discovery, parsing, chunking, embedding, persistence, reporting, and retry orchestration
- Configuration: move to Pydantic settings with environment validation
- FastAPI: add versioned typed schemas and new investigation and approval routers
- Streamlit: retain until the React frontend is ready

### Replace or add

- Add hybrid sparse/dense retrieval and result fusion
- Add source-aware evidence records with document and chunk identifiers
- Add Pydantic investigation domain models
- Replace `MemorySaver` for persistent, resumable investigations
- Add PostgreSQL, migrations, repositories, authentication, and authorization
- Add typed tool registry and mocked deployment, log, monitoring, and incident tools
- Add verification and unsupported-claim checks
- Add LangGraph approval interrupts and persisted approval decisions
- Add retrieval and generation benchmark datasets and executable metrics
- Add streaming investigation events
- Add structured audit logging and request correlation
- Add Docker configuration and production health checks
- Add React/TypeScript frontend or delay this phase until backend phases are stable

## Technical gaps

| Area | Current state | EnterpriseIQ requirement |
|---|---|---|
| Investigation state | Conversation and answer strings | Typed investigation plan, tasks, evidence, findings, hypotheses, unresolved questions, tool calls, approvals, and report |
| Planning | Free-text LLM decision | Structured typed plan with bounded tasks and retry limits |
| Retrieval | Dense Qdrant + reranking | Dense + BM25, fusion, filtering, thresholds, and source metadata |
| Evidence | Chunk strings | Traceable source, document, chunk, excerpt, metadata, score, and timestamp |
| Verification | No citation/consistency verification | Finding classifications and contradiction/unsupported-claim checks |
| Tools | None | Typed, read-only-by-default, permissioned tools |
| Approvals | None | LangGraph interrupts and durable approval records |
| Persistence | In-memory conversation state | PostgreSQL domain data plus persistent LangGraph checkpoints |
| API | Single `/query` endpoint | Authenticated typed investigation, ingestion, evidence, history, approval, and health APIs |
| Ingestion | Batch CLI; local JSON; limited formats | Upload API, incremental ingestion, version tracking, duplicate detection, reports |
| Evaluation | No benchmark framework | Fixed datasets and retrieval/generation/agent/system metrics |
| Security | Environment secrets and basic URL validation | Auth, RBAC/organization boundaries, rate limiting, audit logs, prompt-injection defenses |
| Frontend | Streamlit chat | React incident-investigation interface while retaining compatibility |
| Observability | Logging | Structured logs, tracing, latency, cost, and error metrics |
| Deployment | No container or migration setup | Docker, reproducible setup, migrations, health/readiness |

## Technical debt and reliability risks

1. `app/services/retrieval/qdrant_service.py` silently converts Qdrant/embedding failures into an empty result list.
2. Ranking and retrieval lose payload/source identity after reranking.
3. The responder does not distinguish evidence from unverified model knowledge.
4. The current plan and documents are plain strings or lists; unsupported claims are not detectable structurally.
5. The planner prompt is hard to validate and can output arbitrary text.
6. `MemorySaver` state is lost when the process restarts.
7. The API catches broad provider exceptions and masks provider-specific status.
8. `app/main.py` has no authentication, authorization, request limits, or streaming endpoint.
9. Qdrant collection configuration is hard-coded and embedding dimension changes can require manual rebuild.
10. Ingestion has no upload API, content hash, document version, duplicate detection, or incremental skip policy.
11. Chunking can split mid-sentence and has no overlap, section/heading metadata, or document/chunk stable IDs.
12. Qdrant payload and processed JSON currently contain only text, filename, source type, and chunk index.
13. The codebase mixes global service objects with dependency-oriented functions and has inconsistent typing.
14. Page router and service modules are placeholders.
15. Default test configuration does not add the repository root to `PYTHONPATH`.
16. `test_groq.py` requires a direct `groq` package that is not declared in `pyproject.toml`.
17. No CI configuration, lint/type-check configuration, or integration test isolation is present.
18. No Docker or migration infrastructure is present.
19. `QUADRANT_URL` and collection naming contain spelling/compatibility inconsistencies to retain carefully during refactoring.

## Integration and security risks

- Uploaded or retrieved content is not currently marked untrusted.
- Prompts do not establish that retrieved text cannot override instructions or tool permissions.
- No tool permission model exists.
- No SQL layer exists; when added, parameterization and tenant scoping must be standard from the start.
- No organization-level tenant boundary exists.
- A future PostgreSQL deployment must avoid storing provider secrets or raw external tool results without an audit policy.
- File ingestion needs extension, MIME, size, archive, and executable-content validation.
- External content may contain prompt-injection instructions.

## Current gaps after the local-first implementation

- Operational tools are typed simulations only; deployment, incident, logs, database, and health providers are not connected.
- The default investigation analyst is deterministic and conservative; it does not use a model to correlate complex evidence.
- Contradiction checks recognize only a narrow set of opposing status terms and require human review.
- API-key auth is single-credential-per-deployment. There is no interactive auth, user lifecycle, or production RBAC policy.
- Local rate limiting is process-scoped and should be backed by an API gateway for multi-worker deployments.
- Dense retrieval is opt-in. Legacy Qdrant points without an `organization_id` payload must be re-indexed before tenant-filtered dense search can use them.
- Evaluation data is synthetic. Dense evaluation requires a locally cached sentence-transformer model; report generation, agent outcomes, latency, and cost are exposed as metric functions but are not claimed as benchmark results.
- PostgreSQL is supported through SQLAlchemy/Alembic and the LangGraph Postgres saver, but production PostgreSQL integration, backups, failover, and load behavior have not been tested in this environment.
