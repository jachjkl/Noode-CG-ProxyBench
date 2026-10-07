# General100 + JP10

所有 Qualified 同一延迟/丢失/速度规则。JP hint 不是结果；合格后通过当前 Candidate 查询 ipwho.is、api.country.is，至少一个有效国家代码，两个有效结果冲突则 geo_conflict，不入 JP append。

General200 统一复测选 General100；从其余 JP Qualified 初选20再复测，不足时补后续 JP20。JP 与 General 不重复。

最终100 general +10 jp_append，rank1–110，JP最后十条，IP唯一。不足不降低标准，needs_more 保留 Last Good。CF 入口 hint 不保证 Worker 出口为 JP。
