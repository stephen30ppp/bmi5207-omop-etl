# 11 · 实施结果与审计修订（可用于展示幻灯片）

运行命令：`python -m etl.run --raw <数据目录> --secret secrets/etl.key --out output`（mapping-mode = review）。下文所有数字都来自 `output/` 中的真实输出，可以复核。

## 1. 审计修订落实情况

| 审计项 | 实现 | 代码位置 |
|---|---|---|
| 范围表述：OMOP CDM v5.4-aligned subset | 输出 10 张表；`CDM_SOURCE.source_description` 中写明 | `etl/settings.py` |
| HMAC ID + 每名患者按天偏移 | 同一患者所有事件共用一个偏移 d ∈ ±[30, 365] 天；年份字段通过年中锚点使用同一个 d | `etl/deid.py` |
| Lab 不关联 visit | 162 行 `visit_occurrence_id` 全部为 NULL，由测试断言 | `etl/builders/measurement.py` |
| ICD 补小数点只用于查找候选 | WHO ICD10 同码按 EQUAL 候选处理，需复核；只有父码时标 WIDER；都没有时标 UNMAPPABLE；S7211 的同码匹配被拒绝 | `scripts/build_mappings.py` |
| sig 不拼接剂量 | `sig = NULL`；剂量写入 `intermediate/drug_dose.csv` | `etl/builders/drug.py` |
| source_release_date 只能作为代理值 | 2022-11-07，在 source_description 中注明是代理值 | `etl/settings.py` |
| concept 0 只用于开发阶段 | 已核实的概念都写入真实的 Athena Standard ID；concept 0 只出现在确实无法映射的编码上，而且每一行都有原因 | `validate.py` 中的对账检查 |
| 映射失败的记录保留 | concept_id = 0，并写入 `unmapped_reason`；`unmapped_summary.csv` 按原因汇总 | `etl/router.py` |
| target 必须是 Standard，source 可以不是 | 校验非零 target 的 standard_concept 为 S、有效、且 domain 与所在表一致；`*_source_concept_id` 中可以是非 Standard 的 ICD10 概念 | `etl/validate.py` |
| 稳定的源事件 ID，逐条对账 | 每个源事件有一个 `source_event_key`（基于 HMAC，不含原始 ID），共 527 个，每个都有去向 | `output/lineage/source_event_lineage.csv` |
| Builder 不分配主键、不写 CSV、不自创 concept | Builder 只产出 Event；`router` 决定写入哪张表，`ids` 统一分配主键，`write` 写出，concept 只来自 `mappings/*.csv` | `etl/` |

## 2. 关键结果

### 2.1 输出表

| 表 | 行数 | 说明 |
|---|---|---|
| PERSON | 5 | |
| DEATH | 2 | death_date 取偏移后年份的 12-31 |
| OBSERVATION_PERIOD | 5 | 按最早和最晚事件推断，**不代表期间内的事件都被完整记录** |
| VISIT_OCCURRENCE | 21 | 22 行中精确去重 1 行 |
| CONDITION_OCCURRENCE | 121 | 149 条诊断源事件中，26 条路由到 OBSERVATION，2 条路由到 PROCEDURE |
| OBSERVATION | 32 | 6 条宗教/婚姻 + 26 条由诊断路由过来（外因码、既往史、器械状态等） |
| PROCEDURE_OCCURRENCE | 10 | 7 条手术中有 1 条一对多（冠脉造影 + PTCA）拆成 2 行，另有 2 条来自诊断路由（IVF） |
| MEASUREMENT | 162 | 1 条 `<2.0` 拆成运算符和数值；6 条定性结果 |
| DRUG_EXPOSURE | 170 | 全部标为医嘱（EHR order 32833），quantity、route、sig 都为 NULL |
| CDM_SOURCE | 1 | |

### 2.2 源事件对账：527 个源事件全部有去向

| 去向 | 源事件数 |
|---|---|
| 已写入 | 494 |
| 已写入，但按 domain 路由到了其他表 | 28 |
| 精确重复，已去重 | 1 |
| 未生成（Religion/Marital 为 “No Mapping”，表示未知） | 4 |

### 2.3 术语映射覆盖率（review 模式）

| 领域 | 不同编码 | 已映射 | 编码覆盖率 | 源事件 | 已映射事件 | 事件覆盖率 |
|---|---|---|---|---|---|---|
| 诊断 | 72 | 65 | 90.3% | 149 | 120 | 80.5% |
| 检验 | 64 | 63 | 98.4% | 162 | 161 | 99.4% |
| 药品 | 73 | 63 | 86.3% | 170 | 156 | 91.8% |
| 手术 | 6 | 6 | 100% | 7 | 7 | 100% |

**未映射的原因**（`output/unmapped_summary.csv`）：
- 13 条诊断是 ICD-10-AM 特有码（U73.9、Y92.x2、E09），WHO ICD10 中既没有同码也没有父码。
- 16 条诊断处于 NEEDS_CLINICAL_REVIEW，包括 E14.72 和 Z86.43：WHO 版本中同码或父码的含义与 AM 不同。
- 14 条药品是营养品、护肤品、FFP、成分未核实的 Mylocaine，以及找不到 MDI 剂型的 fenoterol/ipratropium。
- 1 条检验是 “Slide: Reviewed”，属于流程标记，不是检验结果。

### 2.4 校验结果：128 项 PASS，1 项 WARN，0 项 FAIL

唯一的 WARN 是：478 个源事件依赖状态为 PROPOSED 的映射。这些映射的概念已在 Athena 中核实，但还没有第二人审核。小组复核后把 status 改为 APPROVED，再用 `--mapping-mode final` 生成正式结果。

在 final 模式下，只要有固定概念还没有 APPROVED，pipeline 就会直接停止，不会输出未经审核的概念（由测试 `test_final_mode_refuses_unreviewed_mappings` 覆盖）。

## 3. 可以放进幻灯片的映射案例

| 案例 | 源数据 | 处理 | 说明的问题 |
|---|---|---|---|
| 跨版本同码陷阱 | ICD-10-AM `S7211`：“股骨转子间骨折” | WHO ICD10 中 `S72.11` 的含义是“**开放性**转子周围骨折”，**拒绝同码匹配**，改用父码 S72.1，对应 SNOMED 4015503 “Pertrochanteric fracture”（WIDER） | 补小数点后同码 ≠ 同义 |
| Athena 中没有该词表 | `U739`、`Y9222` | Athena 中没有 ICD10AM，concept 填 0，并写明原因 | 不能编造映射 |
| 按 domain 路由 | `Z8643`（既往史）、`Z31.2`（IVF） | 前者进 OBSERVATION（History of event + Maps to value），后者进 PROCEDURE_OCCURRENCE | 一行诊断不一定进 CONDITION 表 |
| 一对多 | 手术码 `ZSD714H`：“Cor. Angio + Angioplasty” | 拆成 2 条 PROCEDURE：4142645 冠脉造影 + 4184832 PTCA | |
| 检验运算符 | B-HCG `<2.0` | value_as_number = 2，operator_concept_id = 4171756 | |
| 定性结果 | ABO 结果 “B”、HBsAg “Non-Reactive” | value_as_concept_id 分别为 4009006 和 4305306 | |
| 医嘱不等于给药 | 170 条药品记录 | drug_type = 32833（EHR order） | |
| 损坏的数据 | Insulin 的剂量单元格变成了 `2022-07-03` | 医嘱记录保留，剂量标为 corrupt_datetime | 不丢整条记录 |

## 4. 仍需人工完成的工作

1. **映射复核**：第二审核人逐行检查 `mappings/*.csv`，填写 reviewer 和 review_date，把 status 改为 APPROVED。重点检查 equivalence = WIDER 的行，以及 rationale 中写有 “reviewer” 的行。
2. **NEEDS_CLINICAL_REVIEW 的 3 行**（E1472、Z8643）：由临床背景的组员决定映射到哪个概念。
3. **U4**：Emergency + A&E 映射为 Inpatient（9201）还是 ER+Inpatient（262），由小组决定后修改 `mappings/visit.csv`。
4. 药品目前大多映射到 Ingredient 层级（WIDER）。如果时间允许，可以细化到 Clinical Drug。
5. 以上完成后运行 `--mapping-mode final` 生成正式结果，并把数字更新到幻灯片。
