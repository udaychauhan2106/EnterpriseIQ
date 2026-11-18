<!-- SYNTHETIC DOCUMENTATION for INC-002 -->
# Synthetic authentication signing-key runbook

Compare token `kid`, active signing-key metadata, validity intervals, and rotation-job output. Check gateway 401 rates separately from service health probes. Confirm cache contents and key distribution across auth instances before attributing failures to Redis. Never write private signing material to incident logs. Coordinate key rotation and token re-issuance with the identity owner.
