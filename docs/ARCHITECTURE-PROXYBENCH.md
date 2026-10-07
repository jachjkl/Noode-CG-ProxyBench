# Architecture

The Windows application registers an independent owner-authenticated runner and dispatches the workflow in this repository. Ubuntu discovers candidates and publishes an immutable handoff commit. Windows verifies the expected SHA-256 after mirror download, with the authenticated runner control channel available as a final fallback.

The first handoff includes both complete feeds and 10,000 official edge candidates. Cloud session history stores all assigned IPs. Later rounds sample fresh edge IPs without refetching either feed. Windows accumulates downloaded pools before runtime validation, preserving untested first-round candidates across failed validation and replenishment.

Each candidate uses an immutable authenticated profile with only `server` and the internal proxy name changed. An application-owned Mihomo core runs in rule mode. A named inbound listener matches `IN-NAME` to the benchmark group; other traffic uses the unrelated fallback rule. Candidate delay requests explicitly name the outbound. Serial downloads and geography requests explicitly use the owned proxy listener and require a matching connection chain.

Batch state is committed through digest-verified snapshots. The current ordinary shortlist and all old ordinary TOP100 nodes receive competition retests; failed retests replace stale passes. Japanese candidates are separately retested until ten eligible exits remain outside the ordinary selection. Exactly 100+10 unique nodes are required.

Windows sends an allowlisted result archive and digest to Ubuntu, which independently validates the publication gate and commits only public output files. A matching acknowledgement clears the exact pending payload while preserving checkpoints. The controller keeps its own runner alive through replenishment and removes its registration when the operation ends.

Each window gets a new session. The primary start action uses that window's identity; explicit resume restores a saved session. Default replenishment continues until the final gate passes, the user stops, or the candidate space is exhausted. The original repository, its runners, the system proxy, and other application cores are outside this component's ownership.
