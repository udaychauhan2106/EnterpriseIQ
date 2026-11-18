<!-- SYNTHETIC DOCUMENTATION for INC-006 -->
# Synthetic memory-pressure runbook

Compare per-container memory after garbage collection with allocation rate, batch size, restart times, and deployment versions. Distinguish application heap growth from cache memory and host pressure. Preserve heap profiles only in approved non-sensitive environments. Roll back or disable the changed workload, then verify fresh workers remain stable over a representative interval.
