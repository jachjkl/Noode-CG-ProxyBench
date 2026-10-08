# Mihomo lifecycle

The manager reads official stable release metadata and verifies its published SHA-256 against downloads from several public mirrors, with the official asset as a fallback. Each mirror attempt has a bounded timeout. On Windows AMD64 it selects the compatible build. Core upgrades are forbidden during an active benchmark. Updates use temporary downloads, an old-binary backup, atomic replacement, startup health checks, and rollback on failure.

Each owned session has a random controller secret and dynamic loopback ports. LAN access and TUN are disabled; rule mode is mandatory. The named inbound rule and exact benchmark-group membership are verified. Delay API calls specify their candidate outbound directly. Unified delay is enabled, matching the owner's active Clash configuration; the reported response excludes handshake differences while still requiring a successful authenticated connection.

Downloads and geography requests use dedicated per-candidate loopback listeners and InName rules, avoiding a shared-selector race. The legacy shared-listener fallback remains serial. The curl source port must match a controller connection whose chain contains that candidate and excludes DIRECT. A missing or incorrect routing proof invalidates the measurement.

Normal exit stops only the owned core, removes its temporary configuration, clears its controller secret, and releases listeners. Orphan cleanup verifies executable identity, PID creation time, and the owned session directory before terminating a process. Other cores are left untouched.
