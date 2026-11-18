<!-- SYNTHETIC DOCUMENTATION for INC-005 -->
# Synthetic downstream-timeout runbook

Separate internal database and application timings from the external payment dependency span. Compare provider request IDs, deadline budgets, retry counts, and gateway responses. Avoid unbounded retries. Confirm recovery with successful synthetic checks and payment reconciliation; external provider telemetry may be unavailable.
