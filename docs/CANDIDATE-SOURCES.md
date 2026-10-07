# Candidate Sources

必需固定源 zip.cm.edu.kg/all.txt、bestcf.pages.dev/lzj/all.txt，每次打开的会话仅首轮全量下载，拒绝截断，不用缓存冒充刷新。首轮核心源失败停止本周期并保留状态。后续自动补测或手动继续不再访问两个固定链接。

官方 ips-v4：额外 10,000 IPv4，容量比例、确定性分散采样，seed 每轮不同；排除固定源及本周期历史。补齐时打散 CIDR 分组次序，防止前半范围截断偏差。

云端 proxybench-session-history.json.gz 按 session_id 保存全部已交接 IP；不只排除已完成测试者。第二、三轮以及手动继续均不能重新引入任何来源的历史 IP。来源数量按实际获取值显示，首轮通常 20,000+，后续固定源不重抓，通常新增 10,000+。

默认可选 JP hint 为 gslege/CloudflareIP/main/JP.txt，验证当前官方范围，非 CF 记 source_invalid。失败可使用限定新鲜度缓存并标 source_from_cache。hint 不等于 trusted_result。

按 IP+真实 Profile 端口合并，保留 source_names/types、priority、jp_hint、first_seen、last_seen；来源端口不覆盖 Profile。最终 110 再按 IP 全局唯一。

授权代理只从 authorized-proxies.local.yaml 显式 enabled+authorized 的本机来源读取并引用真实 .local.yaml，默认关闭，不抓开放代理/住宅扫描/匿名 SOCKS。

交接镜像/CDN：ghfast.top、gh.ddlc.top、cors.isteed.cc、cdn.jsdelivr.net、fastly.jsdelivr.net、gcore.jsdelivr.net、testingcf.jsdelivr.net、gh-proxy.com、ghproxy.net，再到官方 raw/GitHub raw。可用性随网络变化，所有结果校验可信 SHA-256，镜像不接收 GitHub Token，全部失败用可信 Runner channel。
