# Mihomo lifecycle

The manager uses official stable release assets and verifies the published SHA-256. On Windows AMD64 it selects the compatible build. Core upgrades are forbidden during an active benchmark. Updates use temporary downloads, an old-binary backup, atomic replacement, startup health checks, and rollback on failure.

Each owned session has a random controller secret and dynamic loopback ports. LAN access and TUN are disabled; rule mode is mandatory. The named inbound rule and exact benchmark-group membership are verified. Delay API calls specify their candidate outbound directly.

Downloads and geography requests select a candidate serially and read the selection back. The curl source port must match a controller connection whose chain contains that candidate and excludes DIRECT. A missing or incorrect routing proof invalidates the measurement.

Normal exit stops only the owned core, removes its temporary configuration, clears its controller secret, and releases listeners. Orphan cleanup verifies executable identity, PID creation time, and the owned session directory before terminating a process. Other cores are left untouched.
