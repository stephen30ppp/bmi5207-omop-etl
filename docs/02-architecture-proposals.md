# 02 · 两份独立架构方案摘要

两份方案由**两个不同的模型**在互不可见的情况下独立完成，输入完全相同：Phase 0 事实材料、数据画像、CDM v5.4 摘录、Book of OHDSI 摘录。

| | Architect A | Architect B |
|---|---|---|
| 模型 | Claude，通过 `claude -p` 调用，无工具权限 | GPT-5.6，通过 `codex exec --sandbox read-only` 调用，reasoning effort = high |
| 全文 | [03 · Phase 1 A](03-debate-transcript.md) | [03 · Phase 1 B](03-debate-transcript.md) |

两份方案都按 9 个规定章节组织，并逐一回答了 11 个重点问题。下表是双方原始立场的对比，不代表最终决策；最终决策见 [04](04-decisions-and-tradeoffs.md)。

## 1. 立场对比

| 主题 | A（Claude） | B（GPT/Codex） |
|---|---|---|
| 输出表 | 10 张：8 张 + OBSERVATION_PERIOD + CDM_SOURCE | 10 张，并强调这是“OMOP-aligned clinical extract”，算不上完整的 CDM 数据库 |
| 日期偏移 | 每名患者偏移 d = 7k 天（7–364 天，保留星期几）；只有年份的字段偏移 round(d/365.25) 年 | 每名患者偏移**整数年**，所有字段用同一个 year_delta；遇到闰日退回 2 月 28 日 |
| ID | HMAC(secret, Patient_No) 排序后得到 1–5；ID 按“来源模块 × 表”分段 | HMAC 中央 registry；中央 allocator 为每张表从 1 开始编号 |
| lab 与 visit 的关联 | 为 5 个 lab Case_No **各建一条** VISIT_OCCURRENCE（按 ER/Outpatient 推测类型） | 162 行全部 `visit_occurrence_id = NULL`；lab Case_No 只留在 lineage 中 |
| visit_concept | 3 条规则：Emergency+A&E 对应 ER+Inpatient；Day Surgery 对应 Outpatient；其余对应 Inpatient | 规则不明确时填无匹配占位值，人工审核后再填 |
| 诊断映射 | 码中补小数点，先精确匹配 ICD10（WHO），匹配不到截到 4 位并标 WIDER，仍不行转人工 | 先确认 source vocabulary（gate），只用正式的 `Maps to` |
| 映射失败的记录 | concept_id = 0，留在源字段对应的默认表 | 已知 domain 填 0；domain 不明的**放进 quarantine**，不进 CDM |
| 同一 visit 中同一个码既是主诊断又是次诊断 | 只保留主诊断 | 两条都保留 |
| 药品 quantity | 写入单次剂量 | NULL |
| route | 由剂型推断（Tablet 对应口服等） | NULL |
| sig | — | 写 Order_Text |
| 检验单位 | NULL；推断出的单位用来挑选 LOINC | NULL；不推断单位 |
| Religion / Marital | 放 OBSERVATION，日期用观察期起点作代理，“No Mapping”不生成记录 | 放 OBSERVATION，日期用最早事件作代理并标注；如果课程不接受代理日期，就留在 staging |
| source_release_date | ETL 运行日 | 数据抽取日；未知就 fail closed |
| 分工 | P1 集成；P2 demo+手术+APGAR；P3 visit；P4 诊断（72 码）；P5 lab；P6 药品 | 1 集成；2 visit+诊断；3/4 lab；5/6 药品与手术 |
| 可复现性 | stage1/2/3 分层、CI、提供 demo_secret、输出 hash | 25 个输入文件的 SHA256 + schema contract、release manifest |

## 2. 各自的突出贡献

**A 的贡献**
- 发现 Antibody Screen 原文超出 `value_source_value varchar(50)`
- mapping sheet 增加 `equivalence` 列（EQUAL/WIDER/…）
- 按天偏移日期，严格保留间隔和时刻
- ICD-10-AM 无法确认时给出回退路径
- 分工按编码工作量平衡，APGAR 一开始就有明确负责人

**B 的贡献**
- 把 order 和 administration 区分得最清楚
- quantity 和 route 不硬填
- 输入侧的 source contract 与 SHA256
- 一对多映射用 `mapping_group_id` 记录
- 区分 pseudonymisation 和 anonymisation
- 指出“10 张 CSV”的表述需要准确
