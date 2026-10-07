# Candidate sources

The required feeds are `https://zip.cm.edu.kg/all.txt` and `https://bestcf.pages.dev/lzj/all.txt`. Both are read in full once per application session. Records are neither truncated nor replaced with a stale cache. A required-source failure stops preparation and preserves existing results. Later rounds do not revisit these feeds.

Each round samples 10,000 additional IPv4 addresses from the current official Cloudflare ranges. Capacity-proportional sampling, fresh seeds, range diversity, and explicit exclusions prevent deterministic-prefix bias and repeated assignments. Counts reflect actual fetched records; the first pool is normally above 20,000 and later pools normally add 10,000.

Optional Japanese supplemental feeds are checked against official ranges. Invalid entries are reported; source hints are not accepted as exit-country evidence. Optional caches have explicit freshness limits. Authorized proxy sources require locally supplied configuration and explicit authorization; no anonymous credential list is used by default.

`proxybench-session-history.json.gz` tracks all assigned IPs for the current session, including candidates not yet tested. Every source is filtered against this history. The local cumulative queue independently preserves downloaded candidate metadata.

Handoff mirrors and CDNs include ghfast.top, gh.ddlc.top, cors.isteed.cc, cdn.jsdelivr.net, fastly.jsdelivr.net, gcore.jsdelivr.net, testingcf.jsdelivr.net, gh-proxy.com, and ghproxy.net, followed by official raw routes. Each attempt has a deadline and must match the trusted digest. Mirror requests contain no GitHub authentication. Availability is verified per request rather than assumed. The authenticated runner channel can deliver the same checked payload when mirrors fail.
