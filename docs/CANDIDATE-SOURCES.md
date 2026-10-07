# Candidate Sources

必需固定源 zip.cm.edu.kg/all.txt、bestcf.pages.dev/lzj/all.txt，每次新周期全量下载，拒绝截断，不用缓存冒充刷新。核心源失败停止本周期并保留状态。

官方 ips-v4：额外 10,000 IPv4，容量比例、确定性分散采样，seed 每轮不同；排除固定源及本周期历史。补齐时打散 CIDR 分组次序，防止前半范围截断偏差。

默认可选 JP hint 为 gslege/CloudflareIP/main/JP.txt，验证当前官方范围，非 CF 记 source_invalid。失败可使用限定新鲜度缓存并标 source_from_cache。hint 不等于 trusted_result。

按 IP+真实 Profile 端口合并，保留 source_names/types、priority、jp_hint、first_seen、last_seen；来源端口不覆盖 Profile。最终 110 再按 IP 全局唯一。

授权代理只从 authorized-proxies.local.yaml 显式 enabled+authorized 的本机来源读取并引用真实 .local.yaml，默认关闭，不抓开放代理/住宅扫描/匿名 SOCKS。

交接镜像/CDN：ghfast.top、gh.ddlc.top、cors.isteed.cc、cdn.jsdelivr.net、fastly.jsdelivr.net、gcore.jsdelivr.net、testingcf.jsdelivr.net、gh-proxy.com、ghproxy.net，再到官方 raw/GitHub raw。可用性随网络变化，所有结果校验可信 SHA-256，镜像不接收 GitHub Token，全部失败用可信 Runner channel。
