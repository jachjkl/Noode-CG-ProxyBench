# Windows 网页运行包

解压后双击【开始自动优选.vbs】，自动匹配代理，启动本机窗口和云端交接，无需手工安装 Python/Mihomo。

包内官方 embedded Python、PyYAML/psutil、官方 GitHub CLI、Mihomo、Windows curl。约50MB，首次还需下载独立 Runner，窗口显示进度。

GitHub 使用本机 jachjkl 授权，Runner 标签 noode-cg-proxybench、独立 runtime/runner，只为新仓库执行，原 Runner 不变。

云端候选提交为纯公开 IP，多镜像+官方下载均核验可信 SHA-256，全部失败仍有 Runner channel。结果白名单与门槛校验后由 Ubuntu 推送。

没有真实 Profile 可在窗口导入。网络/源/Worker 失败显示真实状态，保留结果与断点。打包白名单排除 .local、运行数据、浏览器资料、Runner 注册和日志。
