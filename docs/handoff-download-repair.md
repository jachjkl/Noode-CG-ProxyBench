# Handoff download deadlines and integrity

The historical downloader could exceed its nominal PowerShell timeout and stall before reaching a working mirror. The replacement uses an isolated Python orchestrator and curl with a per-address total deadline, a bounded connect timeout, and a parent-process timeout. Failure advances to the next source.

Every download must match the trusted workflow-provided SHA-256. Invalid or stale files never replace the existing handoff. Mirrors receive no GitHub credentials. Logs are written separately from the dashboard's managed process log to avoid multiple-writer file-sharing failures.

Legacy regression coverage includes slow HTTP fallback, bad-digest rejection, preservation after complete source failure, and managed logging under Windows locks. Current ProxyBench adds more candidate mirrors and the authenticated runner channel. In the October validation run, ghfast.top returned the immutable candidate package in approximately four seconds with the expected digest.

Successful observations describe that network attempt only; future mirror availability is checked on each request. TLS verification remains enabled.
