<!-- SYNTHETIC DOCUMENTATION for INC-001 -->
# Synthetic payment database pool runbook

Check database connection utilization, acquisition wait time, active transactions, and payment request latency over the same interval. Compare worker concurrency and pool limits before changing either. Trace requests by correlation ID. A high connection count alone does not establish which service exhausted the pool. Recommended baseline for this fictional environment: 20 payment workers and a 100-connection database limit. Escalate if waiters persist after traffic normalizes.
