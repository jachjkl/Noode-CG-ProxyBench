# Windows preview locking and reopen behavior

The baseline had Windows sharing failures during best-effort UI preview replacement and could clear stop markers while a previous local process was still finishing. These fixes remain part of the migration regression suite.

Atomic writes use bounded retries for Windows sharing errors without truncating old files. UI previews may fail temporarily and recover on the next refresh; formal checkpoints and publication remain strict. Reopen logic preserves state while the owned background process is active.

The active ProxyBench list additionally caches unchanged files, serves at most 300 records per page, and skips unchanged table renders. Pause, explicit resume, new-window start, and pending publication have separate lifecycle semantics. See [recovery](RECOVERY.md) for current guarantees.

Browser validation checks desktop and mobile overflow, paging boundaries, distinct adjacent pages, detail dialogs, and JavaScript errors. Legacy rendering microbenchmarks are retained as regression evidence rather than claims about every user's hardware.
