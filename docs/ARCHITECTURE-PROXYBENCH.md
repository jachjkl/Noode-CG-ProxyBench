# ProxyBench 架构

复用解析器、受控工作池、原子写入、Dashboard、候选交接和 Ubuntu 发布。main.py 的 run / local-select / prepare-handoff 已切换到 core/proxybench，旧直连模块不参与新排名。

双击启动网页，自动匹配 Profile，通过所有者 GitHub 授权准备独立 Runner。云端提交纯候选与健康元数据，Windows 按不可变提交 SHA 和可信 SHA-256 下载。镜像失败后 Runner control channel 可恢复同一包。

Windows Profile + Candidate IP 生成 PB 节点，专用 mixed listener 以 IN-NAME 命中 BENCHMARK-PROXY，其他 MATCH,DIRECT。每批一个 Core，Controller Delay 指定 PB，下载/Geo 单并发 curl 显式使用隔离端口并核验 connection chain。

批次提交事务性 checkpoint。最后统一复测 General200 与独立 JP20，严格选 110。白名单 ZIP、digest、Base64 分块交给 Ubuntu 再校验并提交，仅对应摘要确认后清理 pending。

Runner 注册和目录仅属于新仓库，原仓库 Runner、安装目录、Office 插件和系统代理保持原状。

自动控制器为每次打开分配 session_id；点击开始优选使用本窗口会话，点击继续测试可明确恢复原断点。云端保存全部候选 IP 历史，固定来源只在首次抓取，之后所有来源均排除历史。控制器等待 Ubuntu 确认发布并保留本机执行器，再请求下一轮；默认持续补测直到 100＋日本10，或停止、来源用尽。

发布前普通候选前 200 与旧普通 TOP100 全部重新实测竞争，旧日本追加项走单独 JP 复测。110 条最终通过后，节点文本格式保持 IP:port#country。
