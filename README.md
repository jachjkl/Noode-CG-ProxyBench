# Noode-CG-ProxyBench

真实代理环境 Cloudflare Candidate Benchmark。每个候选 IP 使用你本机真实 Worker / EdgeTunnel 协议参数成为独立 Mihomo 节点，质量取决于该代理访问 Internet 的实际表现。

基线：jachjkl/Noode-CG main 3bc8598b1b9e77cc38f7a54c9d75f5e3796fc058。恢复 Tag：baseline-noode-cg-v13.6.2。原仓库源码不参与本项目写入。

## Windows 双击运行

下载 Windows ZIP，解压后双击 **开始自动优选.vbs**，自动打开本机网页窗口。包内带 Python、PyYAML、psutil、GitHub CLI、curl 和 Mihomo。

自动读取本机 Clash Party / Clash Verge / Mihomo 中匹配 Worker 的真实协议配置，准备专属于新仓库的 Windows Runner，衔接：

**Ubuntu 获取候选 → 多镜像下载与 SHA-256 → Windows 真实代理优选 → Ubuntu 校验发布 → 本地确认 pending。**

首次运行下载独立 Runner。GitHub 使用本机 jachjkl 登录授权；运行包不携带 GitHub Token 或代理秘密。没有可用配置时窗口显示“缺少可用代理协议配置”，可导入已有节点链接。不修改系统代理，不关闭已有 Clash/Mihomo。

## 默认测试规则

- 两个固定链接每个新周期全量读取，官方 IPv4 范围额外取 10,000 个唯一候选，JP Supplemental 另计并验证官方范围。
- 每 Batch 默认 100 个 IP；一个独立 Mihomo Core 一次加载最多 100 个独立 Proxy。
- Google、Cloudflare、GitHub 三站连续三轮，共九次实际 Proxy Site Probe。
- 默认平均延迟 <=200ms、请求丢失 0%、三次 2MiB 完整代理下载平均 >=16Mbps（2MB/s）。下载单并发防止带宽竞争和 selector 竞态。
- Cloudflare 优先 cp.cloudflare.com；预检确认 cp 失败且 trace 可用时，整轮统一使用允许的 www.cloudflare.com/cdn-cgi/trace，实际端点写入记录。
- General 初选 TOP200、JP 初选 TOP20 统一复测，输出 General100 + 额外唯一 JP10。JP 必须经真实代理出口 Geo 验证。
- 发布严格要求 100+10+110 个唯一 IP，不足时保留 Last Good 并继续刷新周期。
- Dashboard 修改规则下一 Batch 生效。Pause/Stop 保存状态，Resume 继续未完成批次。

首次大池扫描前必须完成真实 1→10→100 路径验收。失败不解锁 20,000+ 正式扫描。

## 结果与秘密

输出 nodes.txt、nodes.json、nodes.csv、api.json、ip.zip、health.json。真实 Profile、授权代理本机配置、runtime、Controller secret 不上传 GitHub，不进入分发 ZIP。Rule Mode、TUN 关闭、随机 loopback 端口。下载和 Geo 必须有正确 Candidate 的连接链证据，DIRECT 或错误节点结果无效。

仓库公开仅提供源码和公开 IP 数据。代码写入账户仅 jachjkl；GitHub Actions 由所有者授权发布。

## 开发命令

```powershell
python -m pip install -r requirements-dev.txt
python main.py validate
python main.py validate-profile
python main.py validate-runtime
python main.py dashboard --auto-start
python main.py run
python main.py resume
python -m unittest discover -s tests -v
ruff check .
```

run 是本机流水线；双击入口默认云端交接全流程。CI 不执行真实代理测量。旧直连模块保留用于基线恢复，不是正式入口；原工作流在 docs/legacy/update.yml。

文档：ARCHITECTURE-PROXYBENCH、CANDIDATE-SOURCES、MIHOMO、PROXY-PROFILE、BENCHMARK-METHODOLOGY、JP-SELECTION、RECOVERY、WINDOWS-PACKAGE。
