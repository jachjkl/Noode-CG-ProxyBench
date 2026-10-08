# Checkpoints and recovery

`batch-state.json` points to a SHA-256-verified generation snapshot. The snapshot is the transaction boundary for pools, results, phase, and cycle. Commits write the new compressed snapshot before replacing the pointer and retain recent generations. Attempted, qualified, and result files are inspectable derivative views.

Completed candidates are recorded in `partial-batch.json` and restored only when run identity and phase match. Finished candidates are skipped on resume; unfinished candidates are retried. An owned core crash can restart the current unfinished work while preserving completed batches.

Version 1.1.3 runs the local pipeline directly under the desktop controller. Public candidate and core files use multiple mirrors, while authenticated GitHub operations use official endpoints with bounded retries. The controller does not automatically route these operations through the owner's local HTTP proxy. The application detects existing proxy clients and local listeners without changing the owner's VPN or Windows routing configuration. Measured requests still use the isolated candidate's named rule-mode outbound.

Resuming a saved local scan requires no active GitHub connection. If upload or publication fails afterward, the exact pending archive and SHA-256 remain on disk for retry. Neither network failure nor a resumed checkpoint refetches the fixed feeds. The retained optional Runner controller distinguishes a proven renewal failure followed by an `Abandoned` result from an owner cancellation, but the normal desktop path avoids that dependency entirely.

Local stop, pause, abnormal shutdown, and publication failure retain completed measurements. Normal closure after an ordinary completed run clears transient discovery and measurement caches. Published output and the local authenticated profile remain separate from those caches.

The cumulative cloud candidate queue is saved before profile acceptance, so failed validation does not erase untested first-round inputs. Starting in a new window creates a new discovery session; explicit resume retains the saved session and handoff.

Pause waits at bounded checkpoints. Resume removes the pause marker; stop saves state and cleans up the owned core. Rule changes apply to the next batch. Final competitors use one captured ruleset, and any later edit before publication restarts competition under the latest saved rules. Measurements from different profile fingerprints or the former three-observation policy cannot be mixed with current results.

Output replacement has a durable publication transaction backup. A Windows pending archive stores the exact bytes and digest for retry. Only Ubuntu confirmation of the same digest removes that pending payload; checkpoints remain. Source failures, runtime errors, and insufficient qualification never replace the last successful subscription.

Stop-and-save writes the stop checkpoint only. Manual publication is a separate action: it switches at a batch boundary or starts from saved results, retests them, and uploads the resulting selection without another discovery request. A partial manual publication explicitly records `manual_publication: true` and `quota_complete: false`; it must satisfy the same quality rules. A failed upload keeps its exact ZIP and SHA-256 manifest. Pending health is read from that archive, rather than a potentially newer local health report. Optimization timing is saved separately, excludes paused time and closed-window downtime, and resumes with the checkpoint. Normal close still clears transient timing and candidate state.
