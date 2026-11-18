<!-- SYNTHETIC DOCUMENTATION for INC-010 -->
# Synthetic event-sync runbook

Compare source offsets, per-partition acknowledgements, sink commit confirmations, and a sample of event IDs. A low broker lag is not proof of completed destination writes. Check commit ordering and retry records, pause unsafe checkpoint advancement, then replay only from the last verified sink position with duplicate handling enabled.
