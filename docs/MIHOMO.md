# Mihomo 生命周期

官方 Stable，Windows AMD64 compatible，校验官方 asset SHA-256。更新只在任务开始前或结束后，运行中禁止升级。临时下载、旧 Core 备份、原子替换、启动和 Controller Health Check，失败回滚。

随机 Controller secret、动态 loopback 端口、allow-lan false、rule mode、TUN false。named listener 的 IN-NAME 规则和 PB group 成员必须校验。Delay API 指定 PB，不共享默认 selector。

下载与 Geo 串行选节点并读回确认；curl local-port 与 connection.sourcePort 对应，chain 必须含该 PB 且不含 DIRECT。

正常退出停止自有 Core、删除临时 config/secret、释放端口。孤儿清理校验 exe 路径、PID 创建时间与 session 目录，不操作用户其他 Core。
