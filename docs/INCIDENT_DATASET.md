# Nexora Synthetic Incident Dataset

The Nexora Systems dataset is a fictional learning and evaluation environment for EnterpriseIQ. Every artifact is synthetic; it must not be presented as a real production event or customer record.

## Contents

By default, `uv run python -m app.simulator.materialize` creates one directory per scenario beneath `simulator_data/nexora/generated/`:

```text
INC-001/
  incident.json
  timeline.json
  logs/
    application.log
    infrastructure.log
    monitoring.log
  metrics.csv
  deployment_history.json
  technical_documentation/runbook.md
  reports/incident_report.md
  resolution.json
```

Each incident bundle includes:

- Scenario metadata and UTC incident window.
- An ordered event timeline with event IDs, source, service, severity, and correlation ID where applicable.
- Separate application, infrastructure, and monitoring logs.
- Sampled metrics in CSV form.
- Deployment records, a technical runbook, a non-conclusive incident report, and resolution actions.

The event generator uses scenario-specific deterministic random streams derived from the configured seed. Metrics are linearly interpolated from baseline to peak and back toward baseline over the post-resolution window; they are illustrative synthetic values, not telemetry observations. Routine background events are intentionally mixed with incident evidence.

## Ingestion and retrieval

The publisher has an explicit allowlist of public artifact paths; it does not recursively ingest a directory. It uses existing EnterpriseIQ chunking, document records, and retrieval. Each indexed document and chunk is tagged with `source_type=synthetic_simulator`, the scenario ID, and `synthetic=true`. Investigation retrieval is filtered by scenario ID, preventing one scenario's evidence from being mixed with another scenario's evidence.

The generated bundle directory contains no ground-truth file. Separate files are written to `simulator_data/nexora/ground_truth/INC-*/ground_truth.json`. They are not included in the publish allowlist, ordinary lab/tool responses, or the Incident Lab UI. The evaluator reads them offline. Keep this separation in any future export, search, backup, or frontend feature.

## Service catalog

The simulated environment defines API Gateway, Payment Service, Authentication Service, Notification Service, PostgreSQL, Redis, Message Queue, and Monitoring Service. The Payment Gateway is an external simulated dependency, not an additional live service.

## Provenance and safe use

Synthetic markers are included in JSON records, CSV rows, log prefixes, and document headers. The environment has no real infrastructure connections, customer identifiers, or remediation actions. Recommendations in reports are fictional training content and do not execute operational changes.

The corpus is finite and hand-authored. It does not model production traffic distributions, real provider failure modes, true database query plans, cryptographic materials, or all possible causal relationships. Generated event severity is only a simulated observation.
