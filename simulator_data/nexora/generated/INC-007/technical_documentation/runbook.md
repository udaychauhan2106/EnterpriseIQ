<!-- SYNTHETIC DOCUMENTATION for INC-007 -->
# Synthetic duplicate-transaction runbook

Group transaction records by stable order reference, attempt ID, and provider request ID. Distinguish duplicate notifications from duplicate ledger commits. Check request idempotency at the transaction boundary and retry semantics at each hop. Pause unsafe retries, reconcile using the approved finance workflow, and test duplicate delivery before enabling changes.
