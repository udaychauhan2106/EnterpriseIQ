# Synthetic Payment API Incident Evidence

This fictional document is for testing the EnterpriseIQ knowledge-base upload and investigation flow. All times are UTC. The entries are intentionally inconsistent; they do not establish a confirmed root cause.

## Source A: Change calendar

Service: payment-api. Release: 42. At 13:55 on 2026-11-17, the change calendar records the payment-api release 42 deployment as completed. The calendar entry says the rollout covered all production instances and was closed by the release coordinator. At 14:02, the support channel began receiving reports that some charge requests returned HTTP 500. The first report included trace ID pay-8842. At 14:10, the incident lead noted that the failures appeared intermittent and asked the team to compare the release timeline with application logs. No database metrics, host metrics, or deployment automation output were attached to the calendar entry. This record confirms what the calendar says, but it does not prove that release 42 caused the errors or that every instance was healthy.

## Source B: Deployment console note

Service: payment-api. Release: 42. A deployment console note for the same payment-api release 42 says the rollout status was failed at 14:03 on 2026-11-17. The note mentions an incomplete health-check cycle and says the final instance status was not recorded. It does not identify which instances failed or whether traffic was shifted away from them. A separate application log excerpt at 14:04 shows `POST /v1/charges status=500 trace=pay-8842 error="database request timed out after 3s"`. The excerpt contains no database-side trace, pool metrics, or request retry details. The console note differs from the status recorded in Source A. Neither record establishes whether the health check caused the HTTP 500 responses or whether the timeout was a symptom of another issue.

## Runbook guidance

For intermittent payment-api HTTP 500 errors, the runbook asks responders to correlate request trace IDs with application and database logs, compare the affected instance list with the deployment record, and check database connection-pool and latency metrics for the same time window. Record sources and timestamps. Do not infer causation from timing alone. Escalate unresolved status disagreements to the release owner. This sample contains no live telemetry and describes no remediation that has been performed.
