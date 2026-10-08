# Checkpoints and recovery

`batch-state.json` points to a SHA-256-verified generation snapshot. The snapshot is the transaction boundary for pools, results, phase, and cycle. Commits write the new compressed snapshot before replacing the pointer and retain recent generations. Attempted, qualified, and result files are inspectable derivative views.

Completed candidates are recorded in `partial-batch.json` and restored only when run identity and phase match. Finished candidates are skipped on resume; unfinished candidates are retried. An owned core crash can restart the current unfinished work while preserving completed batches.

GitHub control commands and the application-owned Runner inherit explicitly configured HTTP proxy variables. When none are set, Windows applications discover an enabled, reachable loopback HTTP proxy from the current user's Internet Settings. This affects child processes only; Windows proxy settings and the user's Clash core remain unchanged. Loopback controller traffic bypasses this cloud proxy, while measured traffic still uses each isolated candidate's named rule-mode outbound.

If a cancelled job's new owned Runner diagnostics prove a failed job renewal followed by an `Abandoned` result, the controller waits for the previous Worker and candidate core to exit and resumes the same handoff. At most three automatic recoveries are allowed per controller run. They do not consume a candidate round or fetch the fixed feeds again. An owner-cancelled task without that evidence remains stopped. Both outcomes clear stale in-flight indicators, retain the measured results and checkpoint, and display the actual interruption reason. Closing after an infrastructure interruption retains the checkpoint.

The owner-only `proxybench-connection-check.yml` workflow measures at most 100 saved qualified candidates in a separate temporary directory, then holds the real Runner job for 13 minutes. It does not modify the live checkpoint or publish nodes. This diagnoses Runner connectivity beyond the previously observed 12-minute interruption.

The cumulative cloud candidate queue is saved before profile acceptance, so failed validation does not erase untested first-round inputs. Starting in a new window creates a new discovery session; explicit resume retains the saved session and handoff.

Pause waits at bounded checkpoints. Resume removes the pause marker; stop saves state and cleans up the owned core. Rule changes apply to the next batch, while final competitors use one captured ruleset. Measurements from different profile fingerprints cannot be mixed.

Output replacement has a durable publication transaction backup. A Windows pending archive stores the exact bytes and digest for retry. Only Ubuntu confirmation of the same digest removes that pending payload; checkpoints remain. Source failures, runtime errors, and insufficient qualification never replace the last successful subscription.
