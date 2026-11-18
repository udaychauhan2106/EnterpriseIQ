<!-- SYNTHETIC INCIDENT REPORT for INC-007 -->
# Synthetic incident report: INC-007

Two ledger records were observed for one simulated order reference during a window with client retries and delayed responses. A queue redelivery also occurred, but its transaction references differed. The retry path was disabled while reconciliation and a guarded change were prepared.
