# 05 · Source-to-Target 契约（冻结版，CDM v5.4）

**约定**
- 【V】表示已在数据中核实；【H】表示假设，需要按 04 §3 确认。
- 所有 `*_concept_id` 都要等 mapping sheet 达到 APPROVED 才能写入；写不了的填 0。
- 文中**没有出现任何具体的 concept ID**。

## 0. 全局约定

| 项 | 约定 |
|---|---|
| 输出 | 10 张 CSV：PERSON、OBSERVATION_PERIOD、VISIT_OCCURRENCE、CONDITION_OCCURRENCE、DRUG_EXPOSURE、PROCEDURE_OCCURRENCE、MEASUREMENT、OBSERVATION、DEATH、CDM_SOURCE |
| 格式 | UTF-8 无 BOM、逗号分隔、有表头、LF 换行、符合 RFC 4180；NULL 写空字符串 |
| 日期格式 | 日期 `YYYY-MM-DD`；日期时间 `YYYY-MM-DD HH:MM:SS` |
| 列顺序 | 与官方 v5.4 DDL 一致，由 `etl/cdm54_columns.yaml` 统一定义 |
| 主键 | 中央 allocator 分配，每张表从 1 开始，按 (person_id, 偏移后时间, 源 lineage key) 排序，结果确定 |
| 原始 ID 和原始时间 | **不出现在任何输出文件中**。`*_source_value` 只写代码、受控值或伪名 token |
| 映射失败 | concept_id = 0，保留 source_value，列入 `unmapped.csv`（04 D3） |
| quarantine | 只放解析失败的值，写入 `dq_log.csv` |

## 1. patient demo → PERSON / DEATH / OBSERVATION

| 源字段【V】 | 目标 | 规则 |
|---|---|---|
| Patient_No | PERSON.person_id | 中央 registry 分配，见 06 |
| — | PERSON.person_source_value | 伪名 token，例如 `P03`。**不写原值** |
| Gender | gender_concept_id、gender_source_value | Male / Female 映射到 Gender vocabulary（待 Athena 核实） |
| Patient_DOB（年份） | year_of_birth | 按 06 §3 偏移。month_of_birth、day_of_birth、birth_datetime 为 NULL |
| Race = Chinese（5/5） | race_concept_id、race_source_value | 在 Race vocabulary 中查 "Chinese"；没有就填 0 |
| — | ethnicity_concept_id | 0。原文："Only use this field if you have US-based data" |
| Deceased_Ind = True（2 人） | DEATH 表一行 | death_date = 偏移后年份的 12-31（原文："December ... and the last day of the month"）；death_datetime 为 NULL；death_type 按 type 映射表 |
| Religion = Buddhism（3） | OBSERVATION | 属性 concept 为 religious affiliation 类，value_as_concept_id 为 Buddhism 类，value_source_value 写原文；date 用代理日期（04 D10） |
| Marital_Status = Marr'd（3） | OBSERVATION | 属性 concept 为 marital status 类，value 为 Married 类，value_source_value = `Marr'd` |
| "No Mapping"（Religion 2 条、Marital 2 条） | 不生成记录 | 写入 dq_log 计数 |

**期望行数**：PERSON 5，DEATH 2，OBSERVATION（来自 demo）6。

## 2. case visit → VISIT_OCCURRENCE

| 源字段【V】 | 目标 | 规则 |
|---|---|---|
| （整行） | — | 先做**全列精确去重**，22 行变 21 行（DQ1），被删掉的行写入 dq_log |
| Case_No | visit_occurrence_id | 中央 visit registry 分配。**不写入** visit_source_value |
| Patient_No | person_id | 同一个 registry |
| Adm_DateTime / Dis_DateTime | visit_start_date(time) / visit_end_date(time) | 加偏移 d；不使用 Dis_DateTime_Planned |
| Adm_Type_Desc × Referral_Type_From | visit_concept_id | 3 条规则，由人工批准（04 D5） |
| Adm_Type_Desc | visit_source_value | 原值 |
| — | visit_type_concept_id | 按 type 映射表（EHR 类） |
| Referral_Type_From | admitted_from_source_value；admitted_from_concept_id | 原值；concept 填 0 |
| Discharge_Type_Desc | discharged_to_source_value；discharged_to_concept_id | 原值；只有 "Dis. Comm Hosp" 尝试映射，其余填 0 |
| 科室、病房、MDC、CCI、LOS、*_Ind、计数列、Dis_Reason、Dis_DateTime_Planned | **不输出** | 科室和病房文字属于准标识符。LOS 和计数列只用来校验 |

**期望行数**：21。

## 3. case visit → CONDITION_OCCURRENCE（可能按 domain 路由到其他表）

1. 每个去重后的 visit 生成：主诊断 1 条候选，加上 `Secondary_Diagnosis_Codes_Subvention` 按逗号拆分、去空白后的每个元素各 1 条。保留原始顺序，**不对码去重**（04 D9）。
2. 断言：次诊断条数等于 `No_of_Secondary_Diagnosis_Subvention`（22/22 已核实）。**不要使用** `No_of_Secondary_Diagnosis_ICD9`。
3. 候选总数：**149** 条（去重后，已核实）。
4. 按 mapping 的 target_domain_id 路由：
   - Condition 进 CONDITION_OCCURRENCE
   - Observation 进 OBSERVATION（例如外因码、Z 码，【H】）
   - Procedure 进 PROCEDURE_OCCURRENCE（例如 Z312 IVF，【H】）
   - 映射失败的进 CONDITION_OCCURRENCE，concept 填 0

| 字段 | 规则 |
|---|---|
| condition_source_value | 原码，不加小数点，例如 `I2511` |
| condition_source_concept_id | 源 vocabulary 中精确匹配到的 concept；没有填 0 |
| condition_start_date(time) | 所属 visit 的 start |
| condition_end_date | NULL |
| condition_status_concept_id / _source_value | Primary 或 Secondary（Condition Status domain）；source_value 写 `PRIMARY` 或 `SECONDARY` |
| condition_type_concept_id | 按 type 映射表（U6） |
| visit_occurrence_id | 源数据中 Case_No 的显式关联 |

路由到 OBSERVATION 的记录：observation_date 取 visit start；如果有 `Maps to value`，写入 value_as_concept_id。

**对账**：149 × 一对多展开数 = CONDITION + 路由到 OBSERVATION + 路由到 PROCEDURE 的行数之和。

## 4. lab results → MEASUREMENT

| 源字段【V】 | 目标 | 规则 |
|---|---|---|
| Test_Code + Short_Text | measurement_concept_id；measurement_source_value | 映射键为 `Test_Code\|Short_Text`。Test_Code 为空时键为 `NA\|Sodium`，source_value 写 Short_Text |
| Result_Test_Date | measurement_date(time) | 加偏移 d |
| Test_Result | 见下表 | 由 `parse_result()` 统一处理 |
| Minimum_Range / Maximum_Range | range_low / range_high | 只要有原值就写入 |
| — | unit_concept_id、unit_source_value | **NULL**（源数据没有单位） |
| — | measurement_type_concept_id | Lab result 类 |
| Case_No | visit_occurrence_id = **NULL** | 伪名 episode token 写入 lineage（04 D2） |
| Panel_Test_Code、Test_Order、Chapter_Description、Number_of_Tests | 不输出 | Chapter 只在映射时参考 |

| Test_Result 类型（已核实的例子） | value_as_number | operator_concept_id | value_as_concept_id | value_source_value |
|---|---|---|---|---|
| `142`、`142.0` | 142.0 | NULL（原文："Leave it NULL if there's an exact numeric value"） | NULL | 原文 |
| `<2.0` | 2.0 | `<`（Meas Value Operator，待 Athena 核实） | NULL | `<2.0` |
| `Non-Reactive`、`Positive`、`B`、`Mild Lipaemia` | NULL | NULL | 映射结果；映射不到填 0 | 原文 |
| `Reviewed`（Slide） | NULL | NULL | 0 或按 domain 路由 | 原文 |
| Antibody Screen 长句（约 66 字符） | NULL | NULL | Negative 类 | 截断到 50 字符，全文写入 lineage |

**期望行数**：MEASUREMENT 加上路由到其他表的行数，等于 162 × 展开数。

## 5. medication order → DRUG_EXPOSURE

| 源字段【V】 | 目标 | 规则 |
|---|---|---|
| （每个组分一行） | — | MED、FLD、DIL 都生成记录，按 target domain 路由（04 D19） |
| Cluster_Preferred_Name_Code | drug_source_value；drug_concept_id | 映射键。映射时参考描述、Medication_Order_Component_Text 和 Order_Text（品牌名） |
| Order_Creation_Date | drug_exposure_start_date(time) | 加偏移 d |
| — | drug_exposure_end_date | 等于 start_date。这是满足 Required 字段的约定，**不代表实际疗程** |
| — | verbatim_end_date、days_supply、refills | NULL |
| Dosage_Ordered + Dosage_Ordered_Unit | sig = **NULL**；剂量写入 `intermediate/drug_dose.csv` | 审计修订（04 D8）。剂量解析状态分为 ok / range / corrupt_datetime；Insulin 的两条记录**整条医嘱保留**，只把剂量标为 corrupt |
| Dosage_Ordered_Unit | dose_unit_source_value | 原值 |
| — | quantity | **NULL**（04 D6） |
| — | route_concept_id、route_source_value | **NULL**（04 D7） |
| — | drug_type_concept_id | **处方/医嘱类**，不能用给药类（04 D15） |
| Case_No | visit_occurrence_id | 170 行全部能显式关联。入院前的 20 条医嘱照常关联，测试中作为 WARN（DQ3） |

**期望行数**：DRUG 加上路由到其他表的行数，等于 170 × 展开数。

## 6. surgical → PROCEDURE_OCCURRENCE

| 源字段【V】 | 目标 | 规则 |
|---|---|---|
| Surgical_Code | procedure_source_value | 原值；procedure_source_concept_id 填 0（TOSP 预计不在 Athena 中，见 U5） |
| Surgical_Desc | procedure_concept_id | 按描述人工映射到 SNOMED Procedure。`Cor. Angio + Angioplasty` 可能要拆成两条（一对多） |
| operation_date | procedure_date；procedure_datetime = **NULL** | 7/7 与入院时间相同（DQ4） |
| Operation_Table_Code | 不输出 | 【H】TOSP 分级 |
| — | quantity = 1；procedure_type 按 type 映射表 | — |
| Case_No | visit_occurrence_id | 显式关联 |

**期望行数**：7 × 展开数，加上从诊断路由过来的行数。

## 7. 汇总表

| 表 | 规则 | 期望行数 |
|---|---|---|
| OBSERVATION_PERIOD | 每人 1 条。start = 最早事件日期，end = 最晚事件日期，事件包括 visit、lab、drug、procedure，**不包括死亡**；period_type 用推断类 | 5 |
| CDM_SOURCE | source_release_date = 2022-11-07，**这是代理值**，source_description 中已注明（04 D11）；cdm_release_date = ETL 完成日；cdm_version = "v5.4"；vocabulary_version 取下载的 vocabulary | 1 |
