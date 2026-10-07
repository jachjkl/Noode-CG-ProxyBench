# Profile 自动导入

自动读取当前用户的 Clash Party、Clash Verge、.config/mihomo、.config/clash，优先活动客户端和匹配 Worker 的 443 配置。不读取浏览器凭据或缓存。

窗口支持 VLESS/Trojan/VMess 链接或 Mihomo 单节点 YAML。本机配置 config/proxy-profile.local.yaml，gitignore、发布、分发 ZIP 都排除。

支持 protocol、port、uuid/password、network、TLS、SNI、WS Host/path、ALPN、fingerprint 和原生 Mihomo 参数。每 Candidate 只替换 server 和内部 name，其他参数不变。

格式有效不表示节点可用，实际验证三站与下载。缺失/无效立即“缺少可用代理协议配置”，不生成虚假 UUID，不回退 DIRECT。
