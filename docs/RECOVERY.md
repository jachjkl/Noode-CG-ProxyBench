# 续测与恢复

batch-state.json 指向 SHA-256 校验的 generation gzip 快照，是 pool/results/phase/cycle 事务边界。每批先写快照，再原子改指针，保留最近几代。attempted/qualified/results 是派生检查视图。

已完成 Candidate 保存 partial-batch.json，run_id/phase 匹配后合并；未完成重测，完成不重测。Core 崩溃重启并重试未完成输入，前批次保留。

Pause 有界小步骤后等待，Resume 移除 pause 标记，Stop 保存并清理自有 Core。规则下一批生效，竞赛锁同一规则。Profile 更改拒绝混合旧数据。

输出与 health 有发布事务恢复。Windows pending 保存确切包和摘要，重发同一内容，只收到相同摘要的 Ubuntu 成功确认才删除 pending，不删除 checkpoint。

核心来源失败停止周期，JP可选来源失败 warning。错误和不足不能覆盖 Last Good。
