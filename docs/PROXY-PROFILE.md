# Proxy profiles

Automatic import reads the current user's known Clash Party, Clash Verge, Mihomo, and Clash configuration directories. Matching Worker configurations on port 443 and the active client receive priority. Browser credentials are not read.

Import supports VLESS, Trojan, and VMess links and native single-node Mihomo YAML. The local file is `config/proxy-profile.local.yaml`. It is ignored by Git and excluded from public distributions. The explicitly requested owner-only installation package includes this file locally; that package is never a public release asset.

Protocol, port, UUID or password, transport, TLS, SNI, WebSocket Host and path, ALPN, fingerprint, and native options remain immutable within a profile. Candidate construction changes only the server IP and internal name.

Syntax validation does not establish network usability. Core initialization checks 1/10/100 node loading. Site access and the original-package speed probe are evaluated per candidate during selection, with no separate startup bandwidth gate. Missing or invalid configuration fails explicitly; the application neither invents authentication nor substitutes DIRECT traffic.
