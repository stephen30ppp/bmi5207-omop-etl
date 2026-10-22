# 09 · 验证计划

级别说明：**ERROR** 会让 pipeline 失败；**WARN** 写入 `validation_summary.csv`，需要人工复核。

## 1. 输入 contract（ERROR）

| ID | 断言 |
|---|---|
| T-IN-1 | 共 25 个 xlsx，每类 5 个，每个文件只有 `Sheet1` |
| T-IN-2 | 各类文件的列集合与 `profiling/profile_columns.txt` 完全一致 |
| T-IN-3 | 原始行数为 5 / 22 / 162 / 170 / 7，合计 366 |
| T-IN-4 | 25 个文件的 SHA256 写入 manifest，重跑时比对 |
| T-IN-5 | 5 个 Patient_No；在可关联的行中，跨表的 Patient_No 与 Case_No 归属不一致的行数为 0 |

## 2. 行数对账（ERROR）

| 表 | 期望值 |
|---|---|
| PERSON | 5 |
| DEATH | 2 |
| OBSERVATION_PERIOD | 5 |
| VISIT_OCCURRENCE | 21（22 行减去 1 行精确重复） |
| CDM_SOURCE | 1 |
| OBSERVATION（来自 demo） | 6（3 条 Religion + 3 条 Marital；“No Mapping”共 4 条，不生成记录） |
| 诊断 | 149 × 展开数 = CONDITION + 路由到 OBSERVATION + 路由到 PROCEDURE |
| Lab | 162 × 展开数 = MEASUREMENT + 路由到其他表的行数 |
| 药品 | 170 × 展开数 = DRUG + 路由到其他表的行数 + quarantine（只含解析失败的） |
| 手术 | 7 × 展开数 |

每个 visit 的次诊断条数必须等于 `No_of_Secondary_Diagnosis_Subvention`（22/22）。

## 3. 结构与引用完整性（ERROR）

- 所有 Required=TRUE 的字段非空，依据 `cdm54_columns.yaml`。
- 主键唯一，且都是正整数。
- 所有 person_id 都存在于 PERSON 中。
- 所有非空的 visit_occurrence_id 都存在于 VISIT_OCCURRENCE 中，并且 `event.person_id == visit.person_id`。
- 所有非零的 `*_concept_id`：在 vocabulary 快照中存在，`standard_concept = 'S'`，`invalid_reason IS NULL`，domain 与所在表一致。
- 列顺序、数据类型、varchar 长度符合 v5.4（例如 value_source_value ≤ 50）。

## 4. 时间（ERROR / WARN）

| ID | 断言 | 级别 |
|---|---|---|
| T-DATE-1 | 同一患者任意两个事件的间隔与 stage1 相同（只有 P1 能跑，需要 xwalk） | ERROR |
| T-DATE-2 | 每名患者的 \|d\| ∈ [30, 365]，且所有表使用同一个 d | ERROR |
| T-DATE-3 | 出生年 ≤ 所有事件的年份；death_date ≥ 最后一次事件 | ERROR |
| T-DATE-4 | visit start ≤ end；同一患者的住院互不重叠 | ERROR |
| T-DATE-5 | OBSERVATION_PERIOD 覆盖该患者的全部事件 | ERROR |
| T-DATE-6 | 药品医嘱早于所关联 visit 的 start：期望恰好 20 条，提前量 0.6–6.1 小时 | WARN（数量不符时为 ERROR） |
| T-DATE-7 | 手术日期落在所关联的 visit 内 | ERROR |

## 5. 去标识（ERROR）

- T-DEID-1：所有输出文件中，5 个 Patient_No、26 个 Case_No 和全部原始 datetime 字符串的命中数为 0。
- T-DEID-2：同一个 secret 跑两次，输出逐字节相同（幂等，不会重复插入）；换一个 secret，ID 和日期都会变。
- T-DEID-3：输出中没有科室、病房或 Order_Text 的文字。

## 6. 解析单元测试（ERROR）

- `parse_result`：`"142"` 与 `"142.0"` 都解析为 142.0；`"<2.0"` 解析为运算符 `<` 加数值 2.0；`"Non-Reactive"` 进入定性路径；长句截断到 50 字符，全文保留在 lineage。
- `parse_dose`：datetime 对象返回 None 并写入 dq_log；`"0 - 2"` 保留原文写入 sig；正常数值原样保留。
- 诊断拆分：处理空格和逗号；`Y9222` 重复出现时保留两条（DQ8）。

## 7. 临床语义（WARN，人工复核）

- 性别特异项只出现在女性身上：B-HCG、Estradiol、LH、Dilation of cervix、Z312。
- 检验数值落在参考范围的 0.1–10 倍之外时告警；同时检查 range_low < range_high。
- 定性结果没有写进 value_as_number。
- 所有药品的 drug_type 都是处方/医嘱类；quantity 和 route 全部为 NULL。
- 共现合理性：Warfarin 与 I48、Z921、INR 是否同时出现；Aspirin、Prasugrel 与 I214 是否同时出现。

## 8. 覆盖率报告（写入报告的 Results 部分）

按 domain 统计：不同编码的映射率、行映射率，以及 UNMAPPABLE 编码清单（附频次）。如有条件，可以把输出加载到 DuckDB，跑 OHDSI DataQualityDashboard，作为加分项。
