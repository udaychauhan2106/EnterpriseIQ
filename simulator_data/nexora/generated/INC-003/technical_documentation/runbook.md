<!-- SYNTHETIC DOCUMENTATION for INC-003 -->
# Synthetic notification queue runbook

Inspect queue depth, oldest-message age, consumer acknowledgement rate, and notification delivery receipts together. Broker node health does not measure consumer throughput. Compare consumer concurrency changes with backlog growth. Check Redis timeouts as a possible contributor, and compare the affected message IDs across service logs. Historical dashboards may omit acknowledgement lag; missing metrics must be reported as unknown rather than treated as zero.
