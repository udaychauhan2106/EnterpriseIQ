# Synthetic Incident Scenarios

All scenarios below are fictional Nexora Systems incidents. Scenario descriptions and public artifacts are evidence for investigation, not a pre-confirmed root-cause statement. Ground truth is stored separately for offline evaluation.

| ID | Difficulty | Scenario | Evidence and investigation challenge |
| --- | --- | --- | --- |
| INC-001 | Easy | Payment API connection failures | Correlate payment timeouts, database connection utilization, and a worker-concurrency deployment. |
| INC-002 | Medium | Authentication token validation failures | Compare signing-key validity metadata and protected-route 401s with healthy cache and readiness signals. |
| INC-003 | Hard | Delayed notification delivery | Correlate consumer concurrency, queue depth, delivery age, incomplete lag dashboards, and later Redis noise. |
| INC-004 | Medium | API latency from database query regression | Compare endpoint query duration, database scans/read I/O, stable connection use, and a brief cache signal. |
| INC-005 | Medium | Intermittent checkout timeouts | Separate external simulated payment-gateway latency from internal database timing and retry behavior. |
| INC-006 | Hard | Worker memory pressure after release | Reconstruct delayed heap growth, container restarts, garbage-collection pauses, and coincident cache-memory noise. |
| INC-007 | Hard | Duplicate payment records on retry | Distinguish duplicate ledger commits for one order from a separate queue receipt redelivery. |
| INC-008 | Easy | Service unavailable after probe change | Correlate an incorrect readiness-probe path and orchestrator removal with a healthy application route. |
| INC-009 | Medium | Unexpected access from policy scope change | Distinguish valid authentication from an overly broad authorization selector and unrelated policy-cache denials. |
| INC-010 | Hard | Delayed data synchronization | Compare source offsets and destination confirmations despite a healthy broker and misleading aggregate lag dashboard. |

Four scenarios are classified as hard: INC-003, INC-006, INC-007, and INC-010. Hard scenarios include multiple plausible symptoms, delayed or incomplete evidence, conflicting signals, dependent services, or misleading historical/aggregate measurements. Easy scenarios contain direct evidence and fewer affected services.

The generator creates multiple independent source types for each scenario: application logs, infrastructure logs, monitoring logs, metric samples, deployment history, technical documentation, incident reports, and resolution records. Correlation IDs are included where useful but do not by themselves establish causality. Background noise and misleading symptoms require the investigator to assess timing, service dependencies, and contradictory evidence.
