# Ordinary TOP100 and Japanese append TOP10

All qualified candidates use the same response, request-loss, and original-package speed gates. Japanese source hints are discovery metadata, not results. Geography is requested through the same candidate using ipwho.is and api.country.is. At least one valid country code is required; conflicting valid observations disqualify the Japanese append lane.

The ordinary current shortlist and the previous published ordinary TOP100 compete in uniform retests. Ranking selects the best 100 ordinary candidates. Remaining eligible Japanese candidates and previous Japanese append entries are separately retested in small groups until ten pass or the available set is exhausted.

Final output contains 100 `general` records followed by ten `jp_append` records, ranked 1 through 110. All IPs are unique. Japanese append entries must have verified JP geography and cannot overlap the ordinary lane. Insufficient results preserve the last successful publication and request fresh edge candidates without reducing quality thresholds.

An ingress IP's label or Cloudflare range does not establish the Worker's exit country.

Manual publication reserves the best ten currently qualified Japanese candidates before selecting ordinary competitors. Its actual result can be smaller than the automatic 100+10 quota; Japanese entries still require verified geography, all quality limits, unique IPs and the final append order. The cloud panel displays the actual counts for an explicitly confirmed manual partial publication.
