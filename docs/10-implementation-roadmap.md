# 10 · 实施路线图与最终报告

截止日期未知，以下用相对日期 T0+n 表示。**本阶段到此为止，不会自动进入实现，等待人工审查。**

## 1. 最终推荐架构及理由

采用**合并方案**，各项决策见 [04](04-decisions-and-tradeoffs.md) 的 D1–D20。主体结构如下：

- **两层隔离**：只有 P1 接触原始 ID 和 secret（stage1）；其他人只使用去标识后的 stage2。
- **纯函数 builder + 按 domain 路由**：每个 `build_*` 产出 EventRecord，由 `router` 根据映射得到的 target_domain_id 决定写入哪张表，映射失败的写入默认表并填 concept 0。
- **每名患者一个偏移量 d**：datetime 直接加 d，只有年份的字段用同一个 d 作用在年中锚点上。
- **10 张 CDM v5.4 表**，并记录 vocabulary_version。

**选择理由**
1. 修正了两份原始方案中的全部严重规范错误：A 的 quantity、route、虚构 visit；B 的 sig、quarantine 丢行。
2. 日期方案在本数据中可以证明保持时间顺序，也不会因闰日（2016-02-29）出错。
3. ICD-10-AM 和 Athena 无法使用时都有回退路径，不会卡住关键路径。
4. 分工按约 240 个不同编码平衡，交叉审核内置在分工中。

## 2. 双方的分歧和解决依据（摘要）

| 分歧 | 结果 | 决定性证据 |
|---|---|---|
| 整年偏移还是按天偏移 | 按天偏移，加年中锚点 | 已核实的出院时间 2016-02-29 会被整年偏移破坏 |
| lab 是否单独建 visit | 设为 NULL，用配置开关预留 | lab 的 encounter 类型未知；该字段 Required=FALSE |
| quarantine 还是填 concept 0 | 填 0 并写入默认表 | DRUG_EXPOSURE 原文明确规定映射失败时写入 concept 0 |
| ICD 码截断 | 只能作为候选，必须人工批准 | `Maps to` 关系不能用字符串截断代替 |
| quantity、route | 都为 NULL | quantity 定义为“总量”；route_source_value 必须是源数据原值 |
| sig 写什么 | 剂量加单位，不写药名 | sig 定义为“医嘱指令原文” |
| source_release_date | 2022-11-07，取自 xlsx 元数据 | 字段定义为数据抽取日期 |

完整辩论原文见 [03](03-debate-transcript.md)。

## 3. 仍未解决的问题

见 04 §3：U1 课程评分标准，U2 ICD-10-AM，U3 lab 的 Case_No，U4 ER+Inpatient，U5 TOSP，U6 condition_type，U7 Insulin 剂量。**其中 U1–U3 在 Day 2 前必须有答案。**

## 4. 最小可行版本（MVP，优先实现）

目标：**端到端跑通 10 张表，所有 ERROR 级别的测试通过。**（审计修订）全零 concept 的输出只能作为早期集成测试，**不能作为最终成果**；术语映射从第一天起就要并行进行。实施结果见 [11](11-implementation-results.md)。

1. `load` + `clean`：合并 25 个文件、精确去重、拆分诊断、`parse_result`、`parse_dose`。
2. `deid`：registry、偏移量 d、年中锚点。
3. 用占位 mapping（全部填 0）跑通 8 个 builder，加上 OBSERVATION_PERIOD 和 CDM_SOURCE。
4. `write` 按 v5.4 的列顺序写出；完成 T-IN、行数对账、结构、T-DATE、T-DEID 测试。
5. 然后逐个 domain 替换成 APPROVED mapping，每替换一个就重跑全部测试。

MVP 先跑通、mapping 再逐步替换，这样集成风险最早暴露，人工映射也可以和编码并行进行。

## 5. 正式编码前必须通过的质量门

| Gate | 条件 | 负责人 |
|---|---|---|
| G0 | U1（评分标准和提交格式）已确认，或者小组明确同意按本计划推进 | P1 |
| G1 | `ETL_CONVENTIONS.md` 冻结：stage2 列名、EventRecord、mapping schema、输出格式、type concept 映射表 | P1 + 全员签字 |
| G2 | Athena vocabulary 已下载，版本号已记录；或者明确改用网页人工检索 | P1 |
| G3 | U2（ICD-10-AM）有结论；visit_concept 的 3 条规则已人工批准（U4） | P4、P3 |
| G4 | secret 的存放和 demo_secret 的生成方式已定，`.gitignore` 覆盖 stage1 和 registry | P1 |
| G5 | `tests/` 骨架里已经写好输入 contract 和行数对账的期望值（第 09 节），先写测试 | P1 |

## 6. 编码顺序建议

| 阶段 | 时间 | 内容 | 负责人 |
|---|---|---|---|
| 1 | T0+1 | 仓库骨架、`cdm54_columns.yaml`、`load`、T-IN 测试；Athena 下载；抽码脚本 | P1 |
| 2 | T0+2 | `clean`（去重、拆分、解析）+ 单元测试；`deid` + T-DEID / T-DATE；冻结 G1 | P1；P5、P6 写解析器 |
| 3 | T0+2 → T0+4 | 人工 mapping（并行）：各 domain 由 PROPOSED 推进到 APPROVED | 全员 |
| 4 | T0+3 | 用占位 mapping 跑通 8 个 builder（**MVP**） | P2–P6 |
| 5 | T0+4 | `router`、`ids`、`write`、OBSERVATION_PERIOD、CDM_SOURCE；全量对账 | P1 |
| 6 | T0+5 → T0+6 | 换上 APPROVED mapping，生成覆盖率报告，跑临床语义 WARN 检查并复核 | 全员 |
| 7 | T0+7 | 冻结 mapping 快照和 vocabulary 版本；manifest；报告（Methods、Results、Limitations、分工）；APGAR 定稿 | P1 统稿 |

## 7. 交付物清单

- `omop/` 10 张 CSV，`lineage/`，`dq_log.csv`，`unmapped.csv`，`validation_summary.csv`
- `mappings/` 全部 APPROVED 的 mapping CSV，以及 vocabulary 版本号
- `etl/` 源码、`tests/`、`requirements.txt`（锁定 pandas、openpyxl 版本）、`demo_secret`、`README`（一条命令复现：`python -m etl.run --raw DIR --secret FILE --out DIR`）
- 报告和 APGAR 一页稿
