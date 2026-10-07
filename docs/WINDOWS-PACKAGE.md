# Windows 网页运行包

解压后双击【开始自动优选.vbs】，自动匹配代理，启动本机窗口和云端交接，无需手工安装 Python/Mihomo。

包内官方 embedded Python、PyYAML/psutil、官方 GitHub CLI、Mihomo、Windows curl。约50MB，首次还需下载独立 Runner，窗口显示进度。

GitHub 使用本机 jachjkl 授权，Runner 标签 noode-cg-proxybench、独立 runtime/runner，只为新仓库执行，原 Runner 不变。

云端候选提交为纯公开 IP，多镜像+官方下载均核验可信 SHA-256，全部失败仍有 Runner channel。结果白名单与门槛校验后由 Ubuntu 推送。

没有真实 Profile 可在窗口导入。网络/源/Worker 失败显示真实状态，保留结果与断点。打包白名单排除 .local、运行数据、浏览器资料、Runner 注册和日志。

公开包通过 `python scripts/build_windows_package.py` 构建。所有者专用包通过 `python scripts/build_windows_package.py --personal` 单独构建，在 ZIP 内仅额外加入 config/proxy-profile.local.yaml。专用包不上传公开仓库或 GitHub Release；GitHub 授权和 Runner 注册仍由本机自动获取。

开始优选自动执行云端候选、真实路径验收、本地测速与发布。断点继续复用已有交接和完成批次。继续获取 IP 使用同一会话排除集合重新请求候选、与旧普通 TOP100 竞争、JP10 末尾追加。独立执行器贯穿最多三轮自动补测，发布确认后仅删除匹配的 pending，保留检查点。
