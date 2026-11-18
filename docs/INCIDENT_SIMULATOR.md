# Nexora Systems Incident Simulator

The simulator is a local, deterministic mock environment for EnterpriseIQ. All Nexora services, events, metrics, and documents are fictional and explicitly marked **SYNTHETIC**. Nothing in this environment reports actual customer or company production incidents. It does not create containers, databases, queues, cloud resources, or live service failures.

## Integration plan and architecture

The simulator extends the existing EnterpriseIQ interfaces rather than replacing them:

1. `app/simulator/services.py` defines the eight fictional services and dependencies.
2. Scenario definitions and the seeded generator produce ordered event and metric timelines.
3. The materializer writes source-separated artifacts under `simulator_data/nexora/generated`.
4. The existing document chunking and SQL document/chunk records ingest only a fixed public-artifact allowlist. BM25 retrieval remains the existing retrieval path; scenario IDs scope investigation evidence.
5. Existing read-only investigation tools return fixture data only for scenario-scoped investigations. No-scenario behavior remains unchanged.
6. `/api/v1/lab/*` exposes scenario metadata, evidence queries, and run controls. The React dashboard's Incident Lab polls the run API and can launch an investigation using the existing workflow.

## Generate the dataset

From the repository root in PowerShell:

```powershell
uv run python -m app.simulator.materialize
```

This writes ten scenario bundles beneath `simulator_data\nexora\generated\` and separate evaluation truth files beneath `simulator_data\nexora\ground_truth\`. Both locations are included by the Docker build. To materialize one scenario with a seed override:

```powershell
uv run python -m app.simulator.materialize --scenario INC-006 --seed 42
```

The scenario's fixed start time, scenario ID, configuration, and seed determine reproducible artifact bytes. The seed override affects generated artifacts for that materialization.

## Configuration

Edit `config/nexora_simulation.toml`:

| Setting | Meaning |
| --- | --- |
| `event_generation_interval_seconds` | Cadence for deterministic background-noise event opportunities. |
| `incident_duration_seconds` | Generated event and metric window. |
| `service_failure_probability` | Probability that a scenario event marked for failure injection is included. |
| `background_noise_probability` | Probability of a routine background event at each event cadence. |
| `metric_sampling_interval_seconds` | Metric sample cadence; the incident endpoint is always sampled. |
| `scenario_seed` | Default deterministic seed used by materialization and API runs. |

Configuration values are validated when loaded. Scenario-specific metric profiles and event offsets must fit within the configured duration. Metric profiles rise toward their peaks, then return to baseline over the post-resolution portion of the configured window.

## Run the application

Start the existing API and frontend in separate PowerShell terminals:

```powershell
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

```powershell
Set-Location frontend
npm run dev
```

Open `http://127.0.0.1:5173`, select **Incident Lab**, choose a scenario, and start the simulation. The API run clock advances with elapsed wall-clock time; events and samples become visible on run-status reads. The browser refreshes run details every five seconds. The run status changes to `resolved` at the scenario's resolution offset while its post-incident metrics continue to the end of the configured window. A run uses the configured seed and scenario definition; replay starts a new run with the same seed and deterministic event IDs.

## Incident Lab API

All responses and event records are synthetic.

| Method and path | Behavior |
| --- | --- |
| `GET /api/v1/lab/scenarios` | List available synthetic scenarios and affected services. |
| `POST /api/v1/lab/runs` | Start a run. JSON body: `{"scenario_id":"INC-001"}`. |
| `GET /api/v1/lab/runs` | List this process's simulation runs. |
| `GET /api/v1/lab/runs/{run_id}` | Get elapsed time, events, metrics, and generated service observations. |
| `POST /api/v1/lab/runs/{run_id}/stop` | Freeze a running simulation at its current elapsed time. |
| `POST /api/v1/lab/runs/{run_id}/replay` | Start another run with the original scenario and seed. |
| `POST /api/v1/lab/runs/{run_id}/reset` | Remove one run from the in-memory run list. |
| `POST /api/v1/lab/reset` | Clear all in-memory runs. |
| `POST /api/v1/lab/scenarios/{scenario_id}/publish` | Idempotently index the allowlisted public artifacts through EnterpriseIQ's document ingestion path. |
| `GET /api/v1/lab/scenarios/{scenario_id}/logs` | Search generated application, infrastructure, or monitoring logs. |
| `GET /api/v1/lab/scenarios/{scenario_id}/metrics` | Query generated CSV metric samples. |
| `GET /api/v1/lab/scenarios/{scenario_id}/deployments` | Retrieve synthetic deployment records. |
| `GET /api/v1/lab/scenarios/{scenario_id}/health` | Derive observations from generated event severity; this is not a live health probe. |

To launch a scenario investigation, use the existing `POST /api/v1/investigations` contract with `simulation_scenario_id`. The frontend's **Investigate in EnterpriseIQ** action does this for the selected run. This publishes the public scenario evidence and invokes the existing investigation workflow and its scenario-scoped read-only tools.

## Run lifecycle and limitations

The run manager is process-local and intended for the local mock environment. Restarting the API clears active/history run state; generated bundles and indexed documents remain. The reset APIs affect only run state and do not delete uploaded or indexed documents. No event broker or background worker is required: reads reveal the portion of the deterministic timeline whose offsets have elapsed.

Service-health cards are summaries of generated event severities, not probes. Metrics are generated profiles, not measurements from live systems. A custom seed used by the materializer changes fixture bytes; API investigations use the checked-in/default materialized scenario evidence. Keep the configured seed consistent when using generated bundles for investigation.

Ground truth is stored outside generated evidence, excluded from the ingestion allowlist, not returned by the lab APIs or tools, and not rendered in the frontend. The evaluator is a separate offline utility; it must be given investigation exports explicitly.
