# 04 · 裁决、评分与取舍（Phase 3）

**裁决方式**：每一项争议都以 OMOP CDM v5.4 原文（`sources/cdm54_extract.md`）或已核实的数据事实作为依据，不按“哪一方更有说服力”来判断。

**利益冲突声明**：Lead Orchestrator 本身也是 Claude，和 Architect A 是同一个模型家族。为降低偏向，每条裁决都给出可以核对的原文或数据证据。凡是判 A 胜的条目，都附有 B 可以反驳的检查方法。

## 1. 争议裁决

| # | 争议 | 裁决 | 胜方 | 证据 |
|---|---|---|---|---|
| D1 | 日期偏移方式 | **每名患者偏移同一个整数天数 d**，d 从 HMAC 派生，取值 ±[30, 365] 天且不要求是 7 的倍数，所有 datetime 都加 d。只有年份的字段（出生、死亡）**也用同一个 d**：把它作用在该年的年中锚点 Y-07-02 上，取结果的年份。这样全部字段只经过一种变换 | 综合 A、B（详见下方说明） | **B 的整年偏移在本数据中一定出错**：`Case-4-04` 的出院时间是 2016-02-29 15:48（已核实）。偏移非 4 的倍数年会退回 2 月 28 日，LOS 少 1 天。整年偏移还会原样保留月、日、时刻，脱敏强度弱。**A 的做法有两套规则**（B 指出的问题），偏移只有 104 种可能。年中锚点使两类字段共用一个 d；可以证明在本数据中“死亡日期 ≥ 最后一次事件”始终成立（见 06 §3）。由 T-DATE-3 测试验证 |
| D2 | lab 是否挂到 visit | **MVP 中 `MEASUREMENT.visit_occurrence_id` 全部为 NULL**。可共享的 lineage 中保留伪名化的 episode token。不用日期包含规则把 2 行挂到住院上，否则同一个 episode 会被拆开。用配置开关 `lab_episode_as_visit` 预留 A 的方案，课程方确认后再启用 | B | 字段 `Required=FALSE`。VISIT_OCCURRENCE 要求对应 "unique interaction ... receives a medical good or service over a span of time"。lab Case_No 的 encounter 类型未知（K3），A 自己也承认 visit_concept 是推测的 |
| D3 | 映射失败或 domain 不明的记录 | concept_id = 0，写入源字段对应的默认表，并在 lineage 中写明 `unmapped_reason`，**不允许静默丢行**。**（审计修订）concept 0 只能用于确实无法映射的编码；已核实的概念必须写入真实的 Athena Standard Concept ID**（target 的 standard_concept 必须为 S；source_concept_id 可以是非 Standard 概念） | A + 审计 | 同上；另见 09 对账检查 |
| D4 | ICD 码如何匹配 | **（实施核实 + 审计修订）** Athena 当前词表中**没有 ICD10AM，也没有 TOSP**（2026-10-22 通过 Athena API 的 vocabulary facet 核实）。补小数点**只用于查找候选**，不能因为同码就认定跨版本等价：WHO ICD10 中的同码按 EQUAL 候选处理，需要复核；不存在的码取父码，标 WIDER；两者都没有的标 UNMAPPABLE。**实例**：S7211 在 WHO ICD10 中是 S72.11“开放性转子周围骨折”，而源描述是转子间骨折（并非开放性），因此拒绝同码匹配，改用父码 S72.1 | 审计 + 数据 | `Maps to` 不能用字符串匹配代替；S72.1x 的第 5 位在 WHO ICD10 中编码开放/闭合 |
| D5 | visit_concept_id | 3 种已核实组合各写一条规则，**Day 2 前由人工批准**。初始候选：Emergency + A&E（17 次）对应 Inpatient Visit，是否改为 "ER and Inpatient" 由小组决定；Emergency + SOC（2 次）对应 Inpatient Visit；Day Surgery + SOC（2 次，当天出院）对应 Outpatient 类。discharged_to 只在语义明确时映射（"Dis. Comm Hosp"），其余填 0 并保留原值 | 综合 | visit_concept_id 是 Required 字段，"should be standard and belong to the Visit domain"。组合只有 3 种（已核实），完全可以人工决定。B 说得对：“Pat discharged”不能自动认定为 Home |
| D6 | 药品 quantity | NULL | B（A 已承认） | quantity 原文："total amount dispensed or ordered"。单次剂量不是总量 |
| D7 | route | `route_concept_id` 和 `route_source_value` 都为 NULL。剂型只用作映射时的辅助信息 | B（A 已承认） | route_source_value 原文："verbatim value from the source data representing the drug route"，而源数据没有 route |
| D8 | sig | **（审计修订）`sig = NULL`**。源数据没有处方者的用药指令原文；剂量和单位保存在中间表 `output/intermediate/drug_dose.csv`（按 drug_exposure_id 关联）。不使用 Order_Text（它只是药名） | 审计 | sig 原文："verbatim instruction for the drug as written by the provider"。“10 mg”只是剂量，不构成完整指令 |
| D9 | 同一 visit 中重复出现的码 | **全部保留**，每条有自己的 condition_occurrence_id，status 区分主、次诊断。本数据中没有“主诊断同时出现在次诊断”的情况（已核实），但 `Y9222` 在次诊断中重复出现 2 次（DQ8），同样保留 | B | CONDITION User Guide："Record all conditions as they exist in the source data" |
| D10 | Religion / Marital | 写入 OBSERVATION，observation_date 取该患者 OBSERVATION_PERIOD 的起始日，并在 `observation_source_value` 的 lineage 中标注 `date=derived_proxy`。“No Mapping”**不生成记录**，在 dq_log 中计数。预计 3 条 Religion（Buddhism）和 3 条 Marital（Married）。用配置开关支持课程不接受代理日期的情况 | 综合 | observation_date 是 Required 字段，原文："For some observations the ETL may need to make a choice as to which date to choose"，即规范允许 ETL 自行选择日期，但必须写明 |
| D11 | `source_release_date` | **（审计修订）** 填 2022-11-07，但**明确标注为代理值**：它来自 xlsx 的 docProps modified 时间，不能证明真实抽取日期。`CDM_SOURCE.source_description` 写明了这一点；`cdm_release_date` 填 ETL 完成日 | 审计 | 原文："The date the data was extracted from the source system"。文件修改时间 ≠ 抽取时间 |
| D12 | 输出范围的表述 | 交付 **10 张表**，列定义遵循 CDM v5.4 DDL，在报告中称为 "OMOP CDM v5.4–conformant clinical tables"，并记录 vocabulary_version。完整加载 DDL 加 vocabulary 到 DuckDB 作为加分项 | B | `*_concept_id` 依赖 vocabulary 表才能解析 |
| D13 | ID 分配 | 中央 allocator，每张表从 1 开始，按稳定的 lineage 排序。不按模块分段 | B（A 已承认） | — |
| D14 | 检验单位与 LOINC | unit_concept_id 为 NULL。选 LOINC 时优先选不依赖单位的 concept；性质有歧义的（GHB 与 GHB2 两种 HbA1c、Creatinine）标 `NEEDS_CLINICAL_REVIEW`，推断理由写在 rationale 中，需要审核人签字 | B | 原文："If the source data does not include units, set UNIT_CONCEPT_ID to NULL" |
| D15 | Type concept | 按源表、源字段建立 type 映射表：诊断（Mediclaim 和 Subvention 带理赔属性，候选为 EHR billing 类）、药品（处方/医嘱类，**不能用给药类**）、lab（Lab result 类）、visit、procedure、death、observation period（推断类）。Day 2 前人工确认 | B | `drug_type_concept_id` 原文："delineate between prescriptions written vs ... dispensed vs ... administered" |
| D16 | NULL 的写法 | 空字符串 | A | `\N` 不符合 RFC 4180 CSV 约定 |
| D17 | 可复现性 | 记录 25 个输入文件的 SHA256 和 schema contract（B），同时提供 `demo_secret`（A），让评阅者可以完整重跑 | 两者都取 | — |
| D18 | value_source_value 超长 | 截断到 50 字符，完整原文写入 lineage | 综合 | 字段是 varchar(50) |
| D19 | 药品组分（MED/FLD/DIL） | 每个组分一行，按 target domain 路由（例如 FFP 如果不属于 Drug domain，就进其他表）。映射失败的留在 DRUG 表，concept 填 0 | 综合 | 同 D3 |
| D20 | 分工 | 采用 A 的结构，按编码工作量平衡：visit 和诊断分开，lab 和药品各 1 人主做、1 人交叉审核。再吸收 B 的意见：诊断码拆给两个人 | A 为主 | 见 08 |

## 2. 方案评分（针对原始方案，修订前）

评分标准：OMOP 规范正确性 30%、实施可行性 20%、脱敏与一致性 15%、可重复与可测试性 15%、可维护性 10%、六人协作效率 10%。每项 1–10 分。

| 维度 | A | B | 主要依据 |
|---|---|---|---|
| OMOP 规范正确性 (30%) | 6.5 | 7.5 | A：quantity 用错、route 是推断出来的、凭空建 5 个 visit。B：sig 用错、quarantine 违反 DRUG 表关于 concept 0 的约定 |
| 实施可行性 (20%) | 8.0 | 6.5 | A 对 ICD-10-AM、Athena 下载、visit 规则都有回退方案。B 有多处阻塞 gate，缺 metadata 时 fail closed |
| 脱敏与一致性 (15%) | 7.5 | 6.0 | B 的整年偏移在 2016-02-29 上会出错，并保留月、日。A 有两套规则、偏移空间小 |
| 可重复与可测试性 (15%) | 7.5 | 8.0 | B 有输入 contract 和 SHA256。A 有 CI 和 demo_secret |
| 可维护性 (10%) | 8.0 | 7.5 | A 给出了具体的模块和分层 |
| 六人协作效率 (10%) | 8.0 | 6.0 | B 让 1 个人承担 visit 加 72 个诊断码 |
| **加权总分** | **74.0** | **70.0** | |

**严重规范错误**：两份原始方案**都有**，所以**都不能原样批准**。

- A：quantity、route_source_value、虚构 visit。前两项 A 在 Round 1 中已经自行撤回。
- B：sig、quarantine 丢行。

批准的是第 1 节的**合并方案**。分数接近，只用来说明两份方案各自的强弱，最终方案不由分数决定。

## 3. 尚未解决的问题和验证方法

| ID | 问题 | 如何解决 | 负责人 | 截止 |
|---|---|---|---|---|
| U1 | 课程评分标准和提交格式 | 问课程导师或查看 Canvas | P1 | Day 1 |
| U2 | Athena 是否收录 ICD-10-AM | 下载 vocabulary 后执行 `SELECT * FROM vocabulary WHERE vocabulary_id LIKE 'ICD10%'`；没有的话，用 3 个已知码（`I21.4`、`K31.88`、`E14.72`）在 Athena 网页上检索 | P4 | Day 2 |
| U3 | lab Case_No 的语义 | 问课程方。在此之前保持 NULL（D2）。如果确认是急诊或门诊 episode，打开 `lab_episode_as_visit` | P1 | Day 3 |
| U4 | Emergency + A&E 对应 ER+Inpatient 还是 Inpatient | 小组投票并在报告中写明。对分析的影响：只改 visit_concept_id，其他表不受影响 | P3 | Day 2 |
| U5 | TOSP 是否在 Athena 中 | Athena 网页检索 "TOSP" 和 `ESF701I`。预计没有，届时按描述人工映射到 SNOMED | P2 | Day 2 |
| U6 | condition_type 用 EHR 还是 EHR billing | 依据字段名 Mediclaim/Subvention，倾向 billing 类，小组确认 | P4 | Day 2 |
| U7 | Insulin 的真实剂量 | 无法恢复，记入 Limitations | — | — |
