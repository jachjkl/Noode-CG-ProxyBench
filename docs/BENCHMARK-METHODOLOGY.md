# 实测方法

默认 Google=gstatic generate_204（204），Cloudflare=cp.cloudflare.com（200–399），GitHub=github.com（200–399）。Cloudflare 预检 cp 失败而 trace 成功时全轮统一 trace（200），记录 URL。

每 round 全批次完成三个网站再 barrier，默认三轮。保存九次、站点平均、round 平均、总平均。Loss=失败/(rounds×3)。放宽门槛时失败按 timeout 延迟计入平均，失败样本不删除。

默认 loss=0%、平均<=200ms，通过后同一 Candidate 三次 2MiB Cloudflare Speed 下载，正文完整、状态正确、routing proof 必须满足。平均和中位数保存，平均>=16Mbps=2MB/s。MiB 是文件大小，MB 是十进制字节速度。

排名：loss、成功数、平均延迟、round 抖动、下载速度、IP/port 稳定 tie-break。来源和 JP hint 不覆盖实测。

1/10/100 路径验收使用明确记录的诊断阈值验证传输；正式优选仍使用用户保存的生产规则。路径验收失败不解锁大池。
