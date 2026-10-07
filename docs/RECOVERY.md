# Checkpoints and recovery

`batch-state.json` points to a SHA-256-verified generation snapshot. The snapshot is the transaction boundary for pools, results, phase, and cycle. Commits write the new compressed snapshot before replacing the pointer and retain recent generations. Attempted, qualified, and result files are inspectable derivative views.

Completed candidates are recorded in `partial-batch.json` and restored only when run identity and phase match. Finished candidates are skipped on resume; unfinished candidates are retried. An owned core crash can restart the current unfinished work while preserving completed batches.

The cumulative cloud candidate queue is saved before profile acceptance, so failed validation does not erase untested first-round inputs. Starting in a new window creates a new discovery session; explicit resume retains the saved session and handoff.

Pause waits at bounded checkpoints. Resume removes the pause marker; stop saves state and cleans up the owned core. Rule changes apply to the next batch, while final competitors use one captured ruleset. Measurements from different profile fingerprints cannot be mixed.

Output replacement has a durable publication transaction backup. A Windows pending archive stores the exact bytes and digest for retry. Only Ubuntu confirmation of the same digest removes that pending payload; checkpoints remain. Source failures, runtime errors, and insufficient qualification never replace the last successful subscription.
