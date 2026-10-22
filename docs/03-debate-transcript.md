# 03 · Debate transcript（原文，未经编辑）

运行方式：`python3 debate.py`，复用 `../swarm.py` 的 Agent。A = Claude (`claude -p`, 无工具)，B = GPT-5.6 (`codex exec --sandbox read-only`, effort=high)。双方输入相同：`debate/00-shared-facts.md` + `profiling/` + `sources/`。

**轮次说明**：原计划 Phase 1 + 三轮辩论 + 互评共 5 个阶段。应用户要求缩减为 **Phase 1（独立设计）+ Round 1（交叉挑战）** 两个阶段；Round 2（辩护/修订）、Round 3（收敛）、Phase 3（评分）由 Lead Orchestrator 基于官方规范证据裁决，见 [04](04-decisions-and-tradeoffs.md)。注意：在 Round 1 中双方都已主动承认部分错误（A 自我修正 A1–A4，B 在“A 做得更好”一节中采纳多项），这部分等同于 Round 2 的让步。

另：首次运行时原始数据尚未提供，那一轮 Phase 1 结果归档于 `debate/_archive_no_data_run/`，未用于决策。


---

# Phase 1 · Architect A (Claude) 独立方案

<!-- source: debate/p1_claude.md -->

## Architect A：BMI5207 Group 3d OMOP ETL 独立设计方案

**标记约定**

| 标记 | 含义 |
|---|---|
| 【V】 | 已验证。来源是 facts §4 的 profiling 结果，或 CDM v5.4 extract 原文 |
| 【H】 | 假设。每条都附带确认方法 |
| 【待Athena核实】 | 本文出现的 concept ID 都没有在 Athena 中验证过 |

我在本次会话中没有访问 Athena，也没有读取原始文件。

---

### 1. Source-to-Target Mapping

#### 1.1 总体路由

| 源表（行数【V】） | 目标 OMOP 表 |
|---|---|
| patient_demo（5） | PERSON；DEATH（2 行）；OBSERVATION（Religion、Marital_Status） |
| case_visit（22 行，去重后 21） | VISIT_OCCURRENCE；CONDITION_OCCURRENCE。部分诊断码会按目标 domain 路由到 OBSERVATION 或 PROCEDURE_OCCURRENCE（见 §3.4） |
| lab_results（162） | MEASUREMENT（个别按 domain 路由到 OBSERVATION）；另加 5 条 "lab episode" VISIT_OCCURRENCE（见 1.4） |
| medication_order（170） | DRUG_EXPOSURE |
| surgical（7） | PROCEDURE_OCCURRENCE |
| 全部表汇总 | OBSERVATION_PERIOD（5）、CDM_SOURCE（1） |

#### 1.2 patient_demo

| 源列 | 目标字段 | 规则 |
|---|---|---|
| Patient_No【V】 | PERSON.person_id | 由 de-id 模块分配整数 1–5。person_source_value 写伪名 token（如 `P01`），**不写原始 Patient_No** |
| Gender【V】 {Male, Female} | gender_concept_id；gender_source_value | Male→8507，Female→8532（这两个 ID 出现在 Book of OHDSI 摘录中，仍需【待Athena核实】） |
| Patient_DOB【V】，只有年份 | year_of_birth（Required） | month_of_birth、day_of_birth、birth_datetime 置 NULL。年份按 §2.3 做年级平移 |
| Race【V】，5 人都是 Chinese | race_concept_id；race_source_value | 映射到 Race vocabulary 中的 "Chinese"（若存在）【待Athena核实】 |
| （无来源） | ethnicity_concept_id（Required） | 填 0。依据是 extract："Only use this field if you have US-based data" |
| Deceased_Ind / Death_Date【V】，year-only float | DEATH.death_date | 只为 Deceased_Ind=True 的 2 人生成。Death_Date 先按 §2.3 做年级平移，再按 extract 约定补成 12-31（"December is used as the default month, and the last day of the month"）。death_datetime 置 NULL；death_type_concept_id 用 "EHR" 类 type concept【待Athena核实】 |
| Religion、Marital_Status【V】 | OBSERVATION | 见 Q8。"No Mapping" 不生成记录 |

#### 1.3 case_visit → VISIT_OCCURRENCE

| 源列【V】 | 目标字段 | 规则 |
|---|---|---|
| Case_No | visit_occurrence_id | 整数，由 de-id 模块统一分配。visit_source_value **不放 Case_No** |
| Adm_DateTime / Dis_DateTime | visit_start_date(time) / visit_end_date(time) | 平移后写入 |
| Adm_Type_Desc + Referral_Type_From | visit_concept_id | 用一张规则表映射。【H】Emergency + Intra-Hosp A&E → "Emergency Room and Inpatient Visit"（262）；Day Surgery 且同日出院 → "Outpatient Visit"（9202）；其余住院 → "Inpatient Visit"（9201）。以上 ID 都【待Athena核实】。确认方法：列出 (Adm_Type_Desc, Referral_Type_From, LOS_Days) 的全部组合，人工审核 |
| Adm_Type_Desc | visit_source_value | 原值 |
| Referral_Type_From | admitted_from_source_value | 原值；admitted_from_concept_id 默认 0 |
| Discharge_Type_Desc | discharged_to_source_value；discharged_to_concept_id | 经 mapping sheet 映射。"Dis. Comm Hosp" 映射到 Visit domain 中合适的机构类概念，其余映射到 Home 类概念或 0。都【待Athena核实】 |
| （系统固定） | visit_type_concept_id | "EHR"【待Athena核实】 |
| 其余列：MDC、CCI_Score、各类 LOS、*_Ind、计数列、科室/病房、Dis_Reason、Dis_DateTime_Planned | 不映射 | LOS 可以由日期推出。科室和病房文字属于准标识符；本作业规模下不建 CARE_SITE、VISIT_DETAIL。计数列只用于校验（见 Q5） |

#### 1.4 Data-quality 发现（facts §4.3）的逐条处理

| # | 发现【V】 | 处理 |
|---|---|---|
| 1 | Case_No `Case-4-03` 重复两行，40 列完全相同 | 在 staging 层做精确去重（全列比较），22→21。被丢弃的行写入 `dq_log.csv`。这一行的诊断不重复生成 |
| 2 | lab 的 5 个 Case_No 都不在 case_visit 中，每人一个 | **推荐**：为每个 lab Case_No 建 1 条 VISIT_OCCURRENCE（共 5 条，ID 段与住院分开）。start/end 取该 episode 实验室记录时间的 min/max；visit_source_value = `LAB_EPISODE`；visit_concept_id 先按【H】定为 "Emergency Room Visit"，因为 3/5 的 episode 在同日入院前或跨越入院时刻。另外 2 个（Patient-1、Patient-3）没有对应入院，归入 "Outpatient Visit" 还是 0 需要组内决定。这样保留了源数据的 episode 关联，也不把实验室记录错挂到住院上。**备选**：MEASUREMENT.visit_occurrence_id 置 NULL（CDM 允许，字段 Required=FALSE） |
| 3 | 20 条用药医嘱早于本次 Adm_DateTime 0.6–6.1 h | 保留，仍挂在源 Case_No 对应的 visit 上，因为源数据明确给出了这个关联。不改动 visit_start。校验规则允许入院前 ≤24 h 的偏差，作为 WARN 输出 |
| 4 | operation_date 与 Adm_DateTime 7/7 完全相等 | procedure_date 取日期部分；procedure_datetime 置 NULL，因为这个时间很可能只是入院时刻。【H】在文档中说明，无法从数据确认 |
| 5 | Insulin 的 Dosage_Ordered 为 datetime 2022-07-03；Norepinephrine 为 "0 - 2" | Insulin：quantity = NULL，不猜测剂量，写入 dq_log。Norepinephrine：quantity = NULL，sig 写原文 "0 - 2 mcg/kg/min"。解析器必须先判断单元格类型，datetime 对象一律视为损坏 |
| 6 | 出生和死亡只有年份；死亡晚于最后事件 | 见 §2.3。校验平移后 death_date ≥ 最后事件日期 |
| 7 | 同一患者的住院互不重叠 | 作为校验断言保留，lab episode 不参与这条断言 |

#### 1.5 case_visit → CONDITION_OCCURRENCE（拆分规则见 Q5）

| 字段 | 规则 |
|---|---|
| condition_source_value | 原始码，例如 `I2511` |
| condition_source_concept_id | 若 Athena 中有对应源 vocabulary 的 concept 则填写，否则 0 |
| condition_start_date | 所属 visit 的 visit_start_date |
| condition_end_date | NULL |
| condition_status_concept_id | 主诊断对应 "Primary diagnosis"，次诊断对应 "Secondary diagnosis"（Condition Status domain）【待Athena核实】 |
| condition_status_source_value | `PRIMARY` 或 `SECONDARY_SUBVENTION` |
| condition_type_concept_id | 候选 "EHR" 或 "EHR billing record"（Mediclaim 编码带有理赔属性）。组内二选一【待Athena核实】 |

#### 1.6 lab_results → MEASUREMENT

| 源列【V】 | 目标字段 | 规则 |
|---|---|---|
| Test_Code + Short_Text | measurement_concept_id；measurement_source_value | 映射键用复合键 `Test_Code|Short_Text`。4 行 Sodium 的 Test_Code 为空，用 `NA|Sodium`。source_value 写 Test_Code，为空时写 Short_Text |
| Test_Result | value_as_number / value_as_concept_id / operator_concept_id / value_source_value | 见 Q7 |
| Result_Test_Date | measurement_date(time) | 【H】它是采样时间还是出报告时间未知，文档中注明 |
| Minimum_Range / Maximum_Range | range_low / range_high | 源数据为空就保持 NULL |
| （无 unit 列） | unit_concept_id = NULL | 依据 extract："If the source data does not include units, set UNIT_CONCEPT_ID to NULL" |
| Panel_Test_Code、Test_Order、Chapter_Description、Number_of_Tests | 不映射 | Chapter 只作为映射时的辅助信息 |

#### 1.7 medication_order → DRUG_EXPOSURE

| 源列【V】 | 目标字段 | 规则 |
|---|---|---|
| Cluster_Preferred_Name_Code | drug_source_value；drug_concept_id | 映射键。描述文字取 Cluster Description，Order_Text 只作参考（MED 类中有 21 行为空） |
| Order_Creation_Date | drug_exposure_start_date(time) | 平移后写入 |
| （无来源） | drug_exposure_end_date（Required） | 等于 start_date，即单日暴露。文档说明这代表医嘱日期，不是实际疗程 |
| Dosage_Ordered（数值） | quantity | 语义是"单次医嘱剂量"，不是发药总量，文档中明示这一偏离。非数值时为 NULL，见 1.4 #5 |
| Dosage_Ordered_Unit | dose_unit_source_value | 原值 |
| Dosage_Form | route_concept_id | 只对无歧义剂型映射：Tablet/Capsule/Syrup/Mixture → oral，Suppository → rectal，Nasal Spray → nasal，Cream/Lotion → topical。Inj/Inf 无法区分 IV/IM/SC，置 NULL。route_source_value 写 Dosage_Form 并标注"由剂型推断"【H】 |
| （系统固定） | drug_type_concept_id | 医嘱类 type concept（"EHR prescription" 或 "EHR order" 一类）【待Athena核实】 |
| Component_Type_Code {MED, FLD, DIL} | — | 每个组分各生成 1 行。DIL（NaCl 0.9%）也是进入体内的药物，保留。CDM 没有字段表达组分之间的关系，在文档中说明 |
| Case_No | visit_occurrence_id | 170 行都能关联【V】 |

#### 1.8 surgical → PROCEDURE_OCCURRENCE

| 源列【V】 | 目标字段 | 规则 |
|---|---|---|
| Surgical_Code | procedure_source_value | 原值 |
| Surgical_Desc | procedure_concept_id | TOSP【H】预计不在 Athena 中，因此 source_concept_id = 0；按描述人工映射到 SNOMED Procedure concept |
| Operation_Table_Code | 不映射 | 【H】TOSP 分级，在文档中记录 |
| （系统固定） | procedure_type_concept_id | "EHR"【待Athena核实】 |

ZSD714H "Cor. Angio + Angioplasty" 可能需要拆成 1→2 的映射，见 Q9。

---

### 2. Identity de-identification and date handling

#### 2.1 原则

- 唯一授权方：只有 `deid.py`（由 P1 持有）接触原始 Patient_No 和 Case_No。它输出 stage2 去标识化 staging，其他成员只使用 stage2。
- 输出中不出现任何原始 ID（Patient_No、Case_No）、原始时间戳或自由文本（Dis_Reason、科室名、Order_Text）。*_source_value 只放代码、受控值或伪名 token。
- 【V】源数据中没有直接标识符。需要处理的准标识符包括：出生年、死亡年、精确时间戳、ID 字符串、科室/病房文字、罕见诊断。5 人规模下无法实现 k-anonymity。数据是合成数据，报告中如实说明残余风险。

#### 2.2 ID 分配

```
secret = read_secret(path_outside_repo)        # 不进 git，不提交
token(p)      = HMAC_SHA256(secret, "person:" + Patient_No)
person_id     = rank(token) among 5  -> 1..5   # 与源文件顺序无关
visit_occurrence_id = range_base + rank by (person_id, shifted_start, HMAC(Case_No))
```

- 交叉对照表 `xwalk_person.csv` 和 `xwalk_visit.csv` 只存放在 P1 本地，不提交。
- 复现性：持有 secret 时完全确定性。给评阅者附一个 `demo_secret`，生成的结构相同、ID 和偏移不同，可用于复现测试。

#### 2.3 日期平移规则（回答 Q4 的依据）

1. 每位患者一个偏移量：`d = 7·k` 天，其中 `k = 1 + HMAC(secret,"shift:"+Patient_No) mod 52`，再由 HMAC 的另一位决定正负。因此 |d| 在 7–364 天之间，且是 7 的整数倍，星期几不变。
2. 该患者在 5 类表中的所有 datetime 都加同一个 d。时刻（时:分）不变，所以入院前 0.6 h 的医嘱、lab episode 与入院之间的先后关系、LOS 都**精确保留**。
3. 只有年份的字段：`Δy = round(d / 365.25)`，取值 ∈ {-1, 0, 1}。year_of_birth 和 death 年都加 Δy，再按 CDM 约定把死亡日补成 12-31。
   - **不能**先补成 12-31 再按天平移。否则攻击者知道约定后可以直接反推出 d，全部日期就被还原了。
4. 结果：年龄误差 ≤ 1 岁，与源数据本身"只有年份"的精度相同。死亡晚于最后事件这一点由 §7 的测试断言保证。以本数据为例：Patient-4 最后事件 2016-12-17，死亡年 2017；在 Δy=0 的情况下，平移后的最后事件最晚约为 2017-06，仍早于 2017-12-31。

---

### 3. Athena vocabulary mapping process and mapping-sheet schema

#### 3.1 流程

1. **去重抽码**（自动）：每个 domain 生成一个 CSV，含 distinct code、描述和频次。依据 Book of OHDSI："broken out by domain"。规模【V】：诊断 72、实验室 64、药物 73、手术 6、人口学约 6、visit/discharge 规则约 10。
2. **下载 Athena vocabulary bundle**（人工，P1 用浏览器登录完成；脚本访问会返回 403【V】）。选 SNOMED、LOINC、RxNorm、RxNorm Extension、ICD10（WHO）、Gender、Race、Ethnicity、Visit、Type Concept、Condition Status、UCUM、Meas Value Operator、Route。记录 vocabulary_version，CDM_SOURCE 中要用。
   - 若下载不可行，退回到 Athena 网页人工检索。mapping sheet 的 schema 不变。
3. **自动候选**：
   - ICD 码在本地 CONCEPT 表中查找，再沿 CONCEPT_RELATIONSHIP 的 `Maps to` 和 `Maps to value` 得到标准 concept。查找梯度：精确匹配 ICD10 的 `I25.11`；找不到就截到 4 位 `I25.1`，并标 equivalence=WIDER；仍找不到则转人工。
   - 【H】ICD-10-AM 是否在 Athena 中未验证。E099、U739、M85503 这类 AM 特有码预计需要人工处理。次诊断没有描述【V】，WHO ICD10 的 concept_name 可以补上大部分；AM 特有码的描述需要另找 ICD-10-AM 参考资料（可能受许可限制，见风险）。
   - 实验室、药物、手术用 Usagi 批量导入，列为 code、描述、频次、附加信息。
4. **人工审核**：mapper 选定 concept，reviewer（另一人）把状态改为 APPROVED。ETL 只读取 APPROVED 的行。
5. **导出**：可选导出为 SOURCE_TO_CONCEPT_MAP 格式，作为可复现的附件。

#### 3.2 Mapping-sheet schema（全组统一，每个 domain 一个 CSV）

| 列 | 说明 |
|---|---|
| source_table, source_field | 例如 `case_visit`, `Secondary_Diagnosis_Codes_Subvention` |
| source_code, source_description | 实验室用复合键 `Test_Code|Short_Text` |
| source_vocab_hint | `ICD10AM?`、`local_lab`、`local_drug`、`TOSP?`、`free_text` |
| frequency | 源行数 |
| extra_info | 推断单位与区间、剂型、组分类型、所属 Chapter 等 |
| map_seq | 一对多映射时为 1, 2, …（见 Q9） |
| relationship | `Maps to`、`Maps to value`、`manual` |
| target_concept_id, target_concept_name, target_vocabulary_id, target_domain_id, target_concept_class_id, standard_concept | standard_concept 必须为 `S`。target_domain_id 决定路由 |
| value_as_concept_id, value_source_value | 用于定性结果或 Maps to value |
| equivalence | EQUAL、WIDER、NARROWER、INEXACT、UNMATCHED |
| status | DRAFT、PROPOSED、APPROVED、REJECTED、UNMAPPABLE |
| mapper, reviewer, review_date, vocab_version, comment | comment 写证据，例如"由参考区间推断单位为 mmol/L" |

#### 3.3 各 domain 的映射粒度规则

- **药物**：选源数据能支撑的最细粒度。
  - 描述中带强度和剂型，如 "Fentanyl 100mcg/2mL Inj"，映射到 Clinical Drug。
  - 只有成分和剂型，如 "Bisoprolol Fumarate" + Tablet，映射到 Clinical Drug Form。
  - **不得**用 Dosage_Ordered 反推强度，因为剂量不等于规格。
  - 复方（co-amoxiclav、Salmeterol/Fluticasone）映射到单个复方 concept，不拆分成分。
  - 营养品（Glucerna、Resource、Fresubin）、护肤品（QV、Cetaphil）、FFP：若没有标准 Drug concept，则 drug_concept_id = 0，行保留。
- **实验室**：LOINC 的 property 要与推断单位一致。例如 GHB 5.8（%）和 GHB2 40（mmol/mol，IFCC）应选两个不同的 LOINC；Creatinine 80 是物质浓度，对应 µmol/L。
- **手术**：映射到 SNOMED Procedure。

#### 3.4 Domain 路由

由 target_domain_id 决定写入哪张表：

| target_domain_id | 写入表 |
|---|---|
| Condition | CONDITION_OCCURRENCE |
| Observation | OBSERVATION。预计包括 Z8643 既往史、Z921 长期抗凝、多数 W/X/Y/U 外因或场所码 |
| Procedure | PROCEDURE_OCCURRENCE。例如 Z312 IVF 可能落到这里 |
| Measurement | MEASUREMENT |

上面的预计归属都是【H】，以 Athena 结果为准。

UNMAPPABLE 的码写 concept_id = 0，留在源数据的**默认表**（诊断→CONDITION，实验室→MEASUREMENT，药物→DRUG，手术→PROCEDURE），不丢行。

---

### 4. OMOP CDM target tables and field specification

#### 4.1 产出表与关键字段

产出 10 张表，CDM v5.4。所有 Required=TRUE 的字段均依据 extract。

| 表 | 主键 / ID 段 | Required 字段的来源 | type concept【待Athena核实】 |
|---|---|---|---|
| PERSON | person_id 1–5 | gender、year_of_birth、race、ethnicity(=0) | — |
| OBSERVATION_PERIOD | 1–5 | 每人 start = 所有事件最早日期，end = 最晚日期 | "EHR" 或 "Period inferred by algorithm" 一类 |
| VISIT_OCCURRENCE | 1001–1099 住院；1101–1199 lab episode | visit_concept、start、end、type | EHR |
| CONDITION_OCCURRENCE | 2000001+ | concept、start_date、type | EHR / EHR billing record |
| DRUG_EXPOSURE | 3000001+ | concept、start、end(=start)、type | EHR 医嘱类 |
| MEASUREMENT | 4000001+ | concept、date、type | EHR / Lab result 类 |
| PROCEDURE_OCCURRENCE | 5000001+（手术源）；5100001+（由诊断路由而来） | concept、date、type | EHR |
| OBSERVATION | 6000001+（demo）；6100001+（诊断路由）；6200001+（实验室路由） | concept、date、type | EHR |
| DEATH | person_id | death_date | death_type 用 EHR |
| CDM_SOURCE | 1 行 | name、abbreviation、holder、source_release_date（= ETL 运行日）、cdm_release_date、cdm_version_concept_id（查 vocabulary_id='CDM'）、vocabulary_version | — |

**按"来源模块 × 目标表"划分 ID 段的理由**：6 个人可以并行开发而不冲突，看到 ID 就能追溯到来源模块。

#### 4.2 输出格式统一约定

- CSV，UTF-8 无 BOM，逗号分隔，有表头，LF 换行。
- 日期 `YYYY-MM-DD`，日期时间 `YYYY-MM-DD HH:MM:SS`，NULL 写空字符串。
- 列顺序与 OHDSI 官方 v5.4 DDL 一致，由 `cdm54_columns.yaml` 统一定义。
- **注意**：value_source_value 是 varchar(50)。Antibody Screen 的原文 "No common clinically significant…detected" 约 66 字符，会超长。处理办法：value_as_concept_id 映射到 "Negative" 类 concept，value_source_value 存截断到 50 字符的原文，截断记录写入 dq_log。

---

### 5. Python ETL module architecture

```
etl/
  config.yaml          # 路径、cdm_version、ID 段、shift 参数、vocab_version
  cdm54_columns.yaml   # 每表列顺序、类型、required
  load.py      load_raw(kind) -> DataFrame   # 合并5文件, 断言列集合, 加 __src_file
  clean.py     dedup_exact(df); parse_result(s)->(num, op, text); parse_dose(cell)->(num|None, raw)
  deid.py      class Deid(secret): person_id(), visit_id(), shift_dt(pno, dt), shift_year(pno, y)
  vocab.py     load_maps(dir, status="APPROVED") ; lookup(table, code) -> list[MapRow]
  build_*.py   build(staged: dict[str,DataFrame], vocab, ctx) -> list[EventRecord]
  router.py    route(records) -> dict[cdm_table, DataFrame]   # 按 target_domain_id
  ids.py       allocate(cdm_table, source_module, df, sort_keys)  # 确定性排序 + ID 段
  period.py / cdm_source.py
  write.py     write_cdm(table, df)   # 列序/格式/类型强制
  run.py       python -m etl.run --raw DIR --secret FILE --out DIR
tests/  (pytest)
```

**数据分层**

| 层 | 内容 | 是否离开 P1 本机 |
|---|---|---|
| stage1 | 合并、清洗后的数据，仍含原始 ID | 否 |
| stage2 | 去标识化、日期已平移，整数 ID 已就位 | 可共享 |
| stage3 | OMOP CSV 输出 | 可共享 |

- builder 是纯函数，只读 stage2 和 mapping sheet，所以可以单独测试。
- 可复现性：`requirements.txt` 锁定 pandas、openpyxl 版本。运行后输出 `manifest.json`，记录每张表的行数与 SHA256、vocab_version、git commit。

---

### 6. 6-person parallel development and integration strategy

| 成员 | ETL 职责 | Mapping 负责（审核人） | 其他 |
|---|---|---|---|
| P1 Lead/Integration | load、clean、deid、ids、router、write、run、OBSERVATION_PERIOD、CDM_SOURCE；持有 secret；下载 Athena；搭 CI 测试框架 | 无（统一审核 schema） | 最终合并 |
| P2 | PERSON、DEATH、OBSERVATION(demo)、PROCEDURE（手术） | 人口学约 6 项 + 手术 6 码（P1） | **APGAR 一页纸负责人**（修正"用于决定是否复苏"这句表述），因为 ETL 负载最轻 |
| P3 | VISIT_OCCURRENCE（含去重、5 个 lab episode）、visit/discharge 规则表 | visit 规则约 10 条（P4） | 时间关系校验 |
| P4 | CONDITION_OCCURRENCE 拆分与路由 | 诊断 72 码，工作量最大（P3） | 语义校验：性别与诊断的一致性 |
| P5 | MEASUREMENT（结果解析、定性结果、operator） | 实验室 64 项（P6） | 推断单位的证据表 |
| P6 | DRUG_EXPOSURE（剂量解析、组分、route） | 药物 73 项（P5） | 药物与诊断一致性检查 |

这个分工与组内原计划的差异：原计划由 1 人负责 case_visit，这里拆成 visit（P3）与诊断（P4），因为 72 个 ICD 码是最大的映射负担。原计划中 lab 和 med 各 2 人，这里改为 1 人主做加 1 人交叉审核。

**集成方式**

- D2 冻结接口契约 `ETL_CONVENTIONS.md`，内容包括：stage2 列名、mapping-sheet schema、EventRecord 字段、ID 段、type concept 选择、输出格式。
- Git 每人一个分支。合并 PR 需要 P1 加一位同伴审核，CI 跑 pytest 必须全绿。
- 每天由 P1 跑一次全量 `run.py`，把行数对账表发到群里。

---

### 7. Automated tests and quality validation

| 类别 | 断言（失败级别） |
|---|---|
| 单元 | deid 确定性（同 secret 同结果，换 secret 结果变化）；parse_result 覆盖 "142.0"、"<2.0"、"Non-Reactive"、长句；parse_dose 对 datetime 返回 None |
| 行数对账（ERROR） | PERSON=5；住院 visit=21，lab visit=5；MEASUREMENT 与路由出去的行合计 = 162 × 映射展开数；DRUG=170；手术 7 × 展开数；诊断行合计 = Σ去重后各 visit (1 + 次诊断数) × 展开数 |
| 计数一致（ERROR） | 每个 visit 拆出的次诊断数 = No_of_Secondary_Diagnosis_Subvention（profiling 中 22/22 吻合【V】） |
| 完整性（ERROR） | 主键唯一；person_id、visit_occurrence_id 外键都存在；Required 字段非空；所有 *_concept_id 都 ∈ APPROVED 映射或为 0；若有本地 CONCEPT 表，额外检查 standard='S' 且 domain 与所在表一致 |
| 时间（ERROR/WARN） | visit start ≤ end；事件年份 ≥ year_of_birth；事件 ≤ death_date；OBSERVATION_PERIOD 覆盖该人全部事件；measurement 和 procedure 落在所挂 visit 内；drug 允许入院前 ≤24 h（WARN）；同一患者住院不重叠 |
| 平移保真（仅 P1 可跑） | 用 xwalk 对比 stage1 与 stage3：同一患者任意两事件的间隔完全相等；|d| ∈ [7, 364] 且 d % 7 == 0 |
| 去标识（ERROR） | 在所有输出文件中 grep 5 个 Patient_No 和 26 个 Case_No，命中数为 0；任何原始 datetime 都不出现 |
| 临床语义（WARN，人工复核） | 性别特异项（B-HCG、Estradiol、LH、Dilation of cervix、Z312）只出现在女性；数值落在参考区间 0.1–10 倍之外则告警；range_low < range_high；Warfarin 与 I48、Z921、INR 是否共现 |
| 可选 | 把输出装入 DuckDB 跑 OHDSI DataQualityDashboard。DQD 需要 R 和数据库环境，可行性【H】待试 |

---

### 8. Schedule and main risks

截止日期未知【V】，这里用相对日期 T0+n 天表示。

| 里程碑 | 内容 |
|---|---|
| T0+2 | 冻结接口契约；stage1/stage2 产出；完成 Athena 下载；生成各 domain 抽码 CSV |
| T0+6 | mapping sheet 全部进入 PROPOSED；各 builder 用 concept_id=0 的占位跑通 |
| T0+9 | mapping 进入 APPROVED；全量 ETL 跑通且测试全绿 |
| T0+11 | 完成报告（方法、约定、dq_log、局限）；APGAR 定稿 |
| T0+12–14 | 缓冲 |

**主要风险与缓解**

| 风险 | 缓解 |
|---|---|
| Athena 下载受阻 | 改为网页人工检索；schema 不变 |
| ICD-10-AM 不在 Athena | 用 WHO ICD10 截断映射并标 WIDER，AM 特有码人工映射；尽早由 P4 验证 |
| TOSP、本地码没有源 vocabulary | source_concept_id = 0，按描述人工映射 |
| 实验室没有单位 | unit_concept_id 依规范置 NULL；推断单位只用于选择 LOINC 和文档说明 |
| 评分标准与提交形式未知 | **第一优先**向课程方确认 |
| secret 丢失 | P1 与一名备份成员离线保存；提供 demo_secret |
| 约定不一致 | 契约冻结 + CI |
| 范围膨胀 | 不做 ERA 表、CARE_SITE、VISIT_DETAIL |

---

### 9. Answers to the focus questions

**Q1. 只输出 8 张表够吗？**
不够。按 extract，OBSERVATION_PERIOD 每人至少一条（"Each Person needs to have at least one"）。CDM_SOURCE 有多个 Required 字段（vocabulary_version、cdm_version_concept_id 等），是可复现性的元数据。所以至少输出 10 张表，另可附 SOURCE_TO_CONCEPT_MAP。vocabulary 表本身不需要随交付物附上，记录版本号即可。

**Q2. 需要 OBSERVATION_PERIOD 吗？**
需要。没有登记期数据时，按 extract 约定以每人最早和最晚事件推断，生成 5 条。lab episode 和入院前医嘱也纳入计算。Patient-4 跨度 1.5 年中有间隔，仍按 1 条处理，在文档中说明这一假设。

**Q3. 同一患者的 ID 如何在 5 类源表间保持一致？**
所有表都经同一个 `Deid` 实例，用 HMAC(secret, Patient_No) 推出 person_id 和偏移量 d。【V】Patient_No 在 5 类表中 0 不一致。测试会断言每张输出表的 person_id 集合都 ⊆ PERSON。

**Q4. 日期平移会破坏出生、就诊、化验之间的时间关系吗？**
患者内部的时间关系不会被破坏：同一患者所有 datetime 平移同一个 d（7 的倍数），所以间隔、先后顺序、时刻、星期几都保持不变。出生和死亡年按 Δy ∈ {-1, 0, 1} 做年级平移后再补日期，年龄误差 ≤ 1 年，等同于源数据精度。跨患者之间的日历关系会被有意打散。

**Q5. 一次就诊的多个诊断如何正确拆分？**
主诊断 1 行。次诊断字段按逗号 split、去空白、去空值，断言条数等于 No_of_Secondary_Diagnosis_Subvention。每个码生成一个 EventRecord，带相同的 visit_occurrence_id 和 visit_start_date，condition_status 区分主次。然后按映射展开（一对多），再按 domain 路由。同一 visit 内若同一码既是主诊断又是次诊断：先由测试检测是否存在【H】，若存在则只保留 Primary 一行并记入 dq_log。

**Q6. 医嘱与实际给药如何区分？**
源数据只有医嘱，没有给药记录【V】。所以全部 170 行都用医嘱类 drug_type_concept_id，end_date = start_date，quantity 的语义是"医嘱剂量"。不推断任何给药事件，报告中把这一点列为局限。

**Q7. 实验室数值、定性结果和单位如何映射？**
- 数值：统一转成 float，"142.0" 与 "142" 等价，写入 value_as_number。
- `<2.0`：value_as_number = 2.0，operator_concept_id 用 '<'【待Athena核实】。按 extract，"=" 不填。
- 定性结果：Non-Reactive/Positive/B/Mild Lipaemia/抗体筛查长句经 mapping sheet 映射到 value_as_concept_id；没有映射的填 0（extract 约定）；原文写入 value_source_value（≤50 字符）。
- "Reviewed"（Slide）不是检验结果，value_as_concept_id 为 NULL，只保留 source_value。
- 单位：源数据没有，unit_concept_id 为 NULL。推断单位只用于选择 LOINC 和写入文档。

**Q8. Religion 和 Marital Status 放在哪里？**
放 OBSERVATION。observation_concept_id 用 "Religious affiliation" 和 "Marital status" 类属性 concept，value_as_concept_id 用 "Buddhism" 和 "Married" 类 concept，全部【待Athena核实】。value_source_value 写原文（"Marr'd"）。observation_date 取该人 OBSERVATION_PERIOD 的起始日，因为源数据没有采集日期【H】。"No Mapping" 表示未知，不生成记录（与 Book of OHDSI 中"缺失信息不映射"的思路一致）。

**Q9. 映射失败或一对多映射如何处理？**
- 失败：status = UNMAPPABLE，concept_id = 0，行留在默认表中，source_value 保留，并列入未映射清单和频次报告。
- 一对多 `Maps to`：按 map_seq 每个目标生成 1 行（例如 Cor. Angio + Angioplasty 拆成 2 个 PROCEDURE）。
- `Maps to value`：合并为 1 条 OBSERVATION 或 MEASUREMENT，第二个 concept 写入 value_as_concept_id。
- 对账测试按展开后的数量计算期望行数。

**Q10. 如何减少重复的 Athena 人工检索？**
1. 先去重，人工面对的是约 230 个 distinct 码，而不是 366 行原始数据。
2. 下载 vocabulary，用脚本对 ICD 码自动查 Maps to，大部分诊断不需人工。
3. 实验室、药物、手术用 Usagi 批量生成候选。
4. 按频次排序处理。
5. 同成分药物复用结果（例如 Metoclopramide 口服与注射剂、两种 Omeprazole）。
6. 剩余码才去 Athena 网页检索，mapping sheet 预先填好检索词列。
7. 按 domain 分给不同的人并行。

**Q11. 哪些自动化，哪些需要人工审核？**

| 自动化 | 必须人工 |
|---|---|
| 合并、去重、ID 分配、日期平移；字符串解析（结果、剂量、诊断列表）；ICD 自动查 Maps to 候选；domain 路由；写出与格式；全部 §7 测试与对账 | 每一条 mapping 的 APPROVED（mapper 与 reviewer 必须是两个人）；visit_concept 规则表；推断单位与 LOINC property 的选择；AM 和 TOSP 特有码；DQ 发现的处置决定（lab episode 方案、损坏剂量）；WARN 级别的临床语义告警；最终的去标识残余风险说明 |

---

**需尽快向课程方或组内确认的事项**

1. 评分标准与提交形式。
2. lab episode 采用"单独建 visit"还是"visit_occurrence_id 置 NULL"（本方案推荐前者）。
3. condition_type 选 "EHR" 还是 "EHR billing record"。
4. 由谁、何时完成 Athena vocabulary 下载。

---

# Phase 1 · Architect B (GPT/Codex) 独立方案

<!-- source: debate/p1_codex.md -->

### 1. Source-to-Target Mapping

以下设计只使用已核验字段。[已核验] 表示来自 25 个文件的 profiling；[假设] 必须在 ETL 冻结前确认。

#### 1.1 `patient_demo` → `PERSON`、`DEATH`、`OBSERVATION`

| 已核验 source column | OMOP target | 处理 |
|---|---|---|
| `Patient_No` | `PERSON.person_id`；受控 lineage sidecar | 通过唯一中央映射生成整数 `person_id`，绝不直接输出原字符串。`PERSON.person_source_value` 如需调试，只存 HMAC pseudonym，不存原 ID。`person_id` 为必填。[CDM v5.4: `PERSON.person_id`, Required=TRUE] |
| `Patient_DOB`（仅年份） | `PERSON.year_of_birth` | 使用按患者统一平移后的年份；`month_of_birth`、`day_of_birth`、`birth_datetime` 为 NULL。不得补造月日。[`PERSON.year_of_birth`, Required=TRUE；精确生日才填写月、日及 datetime] |
| `Gender` | `PERSON.gender_concept_id`、`gender_source_value` | `Male/Female` 映射到 Standard Gender concept；具体 concept ID 待 Athena 核验。`Gender` 是否表示 biological sex 是[假设]，按 PERSON ETL convention 可在此假设下使用，但须在数据字典确认。[`PERSON.gender_concept_id`, Required=TRUE] |
| `Race`=`Chinese` | `PERSON.race_concept_id`、`race_source_value` | 仅映射经审核的 Standard Race concept，不把 Chinese 推断为 OMOP Ethnicity。若无合适映射，使用无匹配占位并保留 source value。[`PERSON.race_concept_id`, Required=TRUE] |
| 无 ethnicity 字段 | `PERSON.ethnicity_concept_id` | 不推断 Hispanic/Not Hispanic，使用无匹配占位。OMOP 明确不应从 race 推断 ethnicity。[`PERSON.ethnicity_concept_id`, Required=TRUE] |
| `Deceased_Ind`、`Death_Date`（仅年份） | `DEATH.person_id`、`death_date` | 仅两个 `True` 生成 DEATH。年份应用同一患者日期偏移后，按 v5.4 convention 用该年 12 月 31 日作为缺失月日的默认值；`death_datetime` NULL。[`DEATH.death_date`, Required=TRUE；ETL convention：未知月用 December，未知日用 last day] |
| `Religion` | `OBSERVATION` | 社会/生活事实应进入 OBSERVATION，而非 PERSON。[`OBSERVATION` table convention] |
| `Marital_Status` | `OBSERVATION` | 同上。`Marr'd` 映射标准 value concept；`No Mapping` 表示 unknown，不猜测。 |

`Religion` 和 `Marital_Status` 没有采集日期，这是已核验限制，而 `OBSERVATION.observation_date` 必填。我的默认课程级方案是用患者最早 clinical event date 作为明确标注的“derived recording-date proxy”，并在 lineage 中记录 `date_derivation=first_event_proxy`；这不是原始采集日期。[`OBSERVATION.observation_date`, Required=TRUE]。若教师不接受代理日期，则不应伪造日期，应把这两项留在 normalized staging，不生成 OBSERVATION。

预计候选 observation 为每人两条，共 10 条；最终条数取决于 attribute/value concept 是否获人工批准。

#### 1.2 `case_visit` → `VISIT_OCCURRENCE`、`CONDITION_OCCURRENCE`，必要时按 domain 路由

##### Visit

| 已核验 source column | OMOP target | 处理 |
|---|---|---|
| `Case_No` | `visit_occurrence_id` 的中央映射依据 | 不把 Case_No 塞入 `visit_source_value`；该字段表示 visit 类型，不是 encounter identifier。Case crosswalk 仅放在受控 lineage sidecar。 |
| `Patient_No` | `VISIT_OCCURRENCE.person_id` | 通过同一中央 person map 连接。 |
| `Adm_DateTime` | `visit_start_date/datetime` | 患者级统一日期平移。[`VISIT_OCCURRENCE.visit_start_date`, Required=TRUE] |
| `Dis_DateTime` | `visit_end_date/datetime` | 使用实际 discharge，不用 planned discharge。[`visit_end_date`, Required=TRUE] |
| `Adm_Type_Desc` | `visit_source_value`；辅助 `visit_concept_id` | `Emergency` 与 `Day Surgery` 已核验；标准 Visit concept 必须人工审核，ID 待 Athena 核验。 |
| `Referral_Type_From` | `admitted_from_source_value` | 可保留原值；标准 concept 仅在语义审核通过后填入。 |
| `Discharge_Type_Desc` | `discharged_to_source_value` | 比 `Dis_Reason` 更接近 disposition；标准映射人工审核。 |
| `Dis_Reason` | staging/audit | 3 个 NULL，且不一定表示 destination，不强塞进 discharged-to。 |

[假设] `Emergency` 是否应表示 Emergency Room、Inpatient，或 ER followed by Inpatient，不能只凭名称决定。应用 `Adm_Type_Desc`、`Referral_Type_From`、LOS 和 encounter duration 生成候选，再由人工批准。未确认时 `visit_concept_id` 使用无匹配占位，不伪造 Visit concept。[`VISIT_OCCURRENCE.visit_concept_id`, Required=TRUE，且应为 Standard Visit concept]

Departments、subspecialty、ward class 没有已核验的 CARE_SITE 主数据，因此不创建 `care_site_id`。LOS 和各类 LOS 仅用于验证 `Dis_DateTime-Adm_DateTime`；MDC、CCI、指标及计数字段保留在 staging/QC，不为扩大范围而全部转成 OBSERVATION。

##### Diagnoses

- 每个 deduplicated visit 先生成一个 visit。
- `Primary_Diagnosis_Code_Mediclaim` 生成一条 diagnosis candidate，status=`primary`。
- 将 `Secondary_Diagnosis_Codes_Subvention` 按逗号拆分、trim、保留原顺序；每个 list element 生成独立 candidate，status=`secondary`。
- 使用 `No_of_Secondary_Diagnosis_Subvention` 做计数验证，因为已核验 22/22 相等；不使用名称含 `ICD9` 的计数字段驱动解析，因为它只在 12/22 相等。
- 每个 candidate 经过 vocabulary domain routing：
  - 目标 Standard domain=`Condition` → `CONDITION_OCCURRENCE`；
  - 外因、history/status 等若 Athena 映射到其他 domain → 路由到相应表，例如 OBSERVATION；
  - domain 不确定 → quarantine，不能把 W/X/Y/Z/U code 一律强塞入 Condition。
- `condition_start_date/datetime` 使用 visit admission；`condition_end_date` NULL，因为 discharge 不等于疾病结束。
- `condition_status_source_value` 保存 `primary`/`secondary`；对应 standard status ID 待 Athena 核验。
- `visit_occurrence_id` 使用明确的 Case_No link。[`CONDITION_OCCURRENCE.visit_occurrence_id`, Required=FALSE，但规范建议尽力关联]
- 不合并同一 visit 内重复 diagnosis，除非它来自已确认的整行重复；OMOP 允许同一 visit 多个 condition instance。[`condition_occurrence_id`, Required=TRUE；ETL convention]

#### 1.3 `lab_results` → `MEASUREMENT`

| 已核验 source column | OMOP target | 处理 |
|---|---|---|
| `Patient_No` | `person_id` | 中央映射。 |
| `Test_Code`、`Short_Text` | `measurement_concept_id`、`measurement_source_value` | 以 `(Test_Code, Short_Text, Chapter_Description)` 作为 mapping key；4 条 `Test_Code=NULL` 的 Sodium 使用明确的 local fallback key，例如 `NAME:Sodium|CHEMISTRY`，不编造代码。 |
| `Result_Test_Date` | `measurement_date/datetime` | 统一平移。 |
| `Test_Result` | number/operator/concept/source | 见下文。 |
| `Minimum_Range`、`Maximum_Range` | `range_low`、`range_high` | 仅在原值存在且可安全解析时写入。 |
| 无 unit column | `unit_concept_id=NULL`、`unit_source_value=NULL` | 不根据 test name、result 或 reference range 自动猜 unit。[`MEASUREMENT.unit_concept_id`, Required=FALSE；source 无 unit 时应为 NULL] |
| `Panel_Test_Code`、`Test_Order`、`Chapter_Description` | mapping context / audit | 不直接生成额外 clinical event。 |
| `Case_No` | lineage sidecar | 不直接创建 visit link。 |

Result 规则：

- 精确数值，例如 `142`、`142.0`：解析到 `value_as_number`，保留原字符串于 `value_source_value`。
- `<2.0`：`value_as_number=2.0`，`operator_concept_id` 映射 `<`，具体 ID 待 Athena 核验。
- `Non-Reactive`、`Positive`、`B`、`Mild Lipaemia`、`Reviewed`：经人工批准后写 `value_as_concept_id`；未获映射则使用无匹配占位，并保留 `value_source_value`。
- 自由文本 antibody-screen sentence：不强行概念化；保留 `value_source_value`，`value_as_concept_id` 为无匹配占位。
- `GHB` 5.8 与 `GHB2` 40 可能对应不同 HbA1c 单位是[假设]；因没有 unit，不得据数值自行判定百分比或 mmol/mol。

全部 162 条 lab 的 `visit_occurrence_id` 默认 NULL。已核验 lab Case_No 与 visits 0/5 匹配，且只有 2/162 恰好落入 admission window；这不足以推断 encounter。OMOP 允许该 FK 为空。[`MEASUREMENT.visit_occurrence_id`, Required=FALSE]

#### 1.4 `medication_order` → `DRUG_EXPOSURE`

这些是 medication orders，不是 administration records。

| 已核验 source column | OMOP target | 处理 |
|---|---|---|
| `Cluster_Preferred_Name_Code` | `drug_source_value`、mapping key | 本地代码，保留原值。 |
| `Cluster_Preferred_Name_Description`、`Medication_Order_Component_Text`、`Dosage_Form`、`Strength_Unit` | mapping context | 用于选择恰当产品/ingredient，但不推断 route。 |
| `Order_Creation_Date` | `drug_exposure_start_date/datetime` | OMOP 明确允许使用 order date。[`DRUG_EXPOSURE.drug_exposure_start_date`, Required=TRUE；ETL convention] |
| 无 end date/duration | `drug_exposure_end_date=start_date` | 这是满足必填字段的课程级 ETL convention，不表示当天实际服用完毕；`verbatim_end_date`、`days_supply` 为 NULL。[`drug_exposure_end_date`, Required=TRUE] |
| `Order_Text` | `sig` | 仅在非空时原样保存；不构造不存在的 frequency/duration 指令。 |
| `Dosage_Ordered_Unit` | `dose_unit_source_value` | 保存 source unit。 |
| `Dosage_Ordered` | lineage/audit | 它是 per-dose 信息而非明显的 total quantity，不应直接填 `quantity`。 |
| 无 route | `route_concept_id/source_value=NULL` | 不从 `Dosage_Form` 推断 route。 |
| `Case_No` | `visit_occurrence_id` | 所有 med Case_No 均明确链接 visit，因此保留 FK。 |

`drug_type_concept_id` 必须选择表示 prescription/order、而非 administration 的 Type Concept，具体 ID 待 Athena 核验。[`DRUG_EXPOSURE.drug_type_concept_id`, Required=TRUE]

`MED/FLD/DIL` 是 component 类型。相同 Case_No 和 timestamp 的 component 不合并；每个 source component 保留 lineage。若一个组合产品产生多个有效 `Maps to`，按一对多规则生成多条 `DRUG_EXPOSURE`，共享 source lineage 和 mapping group。

两条 insulin 的 `Dosage_Ordered=2022-07-03`：

- 不猜成 “3–7 units”；
- drug order 本身可保留；
- dose value 标为 quarantined/invalid，`quantity` NULL；
- 报告列为需 source-owner 确认。

Norepinephrine 的 `0 - 2 mcg/kg/min` 是 rate range，不是 total quantity，保留于 source audit，`quantity` NULL。

#### 1.5 `surgical` → `PROCEDURE_OCCURRENCE`

- `Surgical_Code`、`Surgical_Desc`：映射到 Standard Procedure concept；TOSP 身份仅为[假设]，先作为 `LOCAL_SURGICAL` 处理。
- `operation_date` → `procedure_date`。
- 因 7/7 `operation_date == Adm_DateTime`，[假设]时间可能是 admission copy。默认仅使用日期部分，`procedure_datetime=NULL`；若数据所有者确认是真实手术时间，再启用 datetime。
- `Case_No`、`Patient_No` 明确关联 visit/person。
- `quantity=1`。
- `Operation_Table_Code` 是 TOSP complexity grade 仅为[假设]；未经确认不填 `modifier_concept_id`，只留 staging/audit。
- procedure source 与 target concept 必须满足 Procedure domain。[`PROCEDURE_OCCURRENCE.procedure_concept_id`, Required=TRUE；ETL convention]

#### 1.6 对 facts §4.3 每项发现的明确处理

1. **重复 visit**：先按全部 40 列识别并移除一条 exact duplicate，得到 21 visits；相关诊断只展开一次。
2. **lab Case_No 不链接**：全部 162 条 measurement 的 visit FK 默认 NULL；不创建 5 个虚构 visit。
3. **20 条 medication 在 admission 前**：保留 source Case_No 的显式 visit link和原时间，列为预期 temporal exception；“A&E order”只是[假设]，不移动时间或扩展 visit。
4. **7/7 surgery time 等于 admission**：保留 procedure date，默认不输出不可信的 procedure time。
5. **Excel dose corruption**：两条 insulin quarantine；Norepinephrine range 不转 quantity；不猜值。
6. **出生/死亡仅年份**：不补生日月日；death 按 v5.4 的 12 月 31 日规则；统一年份偏移。
7. **时间范围、无 visit overlap、Patient_No 一致**：转成 regression assertions；日期平移后必须保持事件次序、无 visit overlap 和所有 FK 的 person 一致性。

---

### 2. Identity de-identification and date handling

#### 2.1 唯一身份权威

由一名 integration owner 生成两个中央 registry：

- `person_registry`: raw `Patient_No` → HMAC token → integer `person_id`
- `visit_registry`: `(Patient_No, Case_No)` → integer `visit_occurrence_id`

所有五类 source 必须 join 同一 registry，禁止各成员自行编号。lab 的 5 个 Case_No 只进入 `source_episode_registry`，不进入 `visit_registry`。

推荐顺序：

1. 从五类文件取得全部 distinct `Patient_No`；
2. 验证恰为 5 个且跨表无未知 patient；
3. 使用带 namespace 的 HMAC-SHA256；
4. 按稳定 HMAC token 排序后分配小整数 OMOP key；
5. 重新运行时使用同一 secret 和 registry，得到相同 ID；
6. raw-to-pseudonym crosswalk 不提交、不写日志。

Secret 从 environment/secret store 注入，repository 只保存 `secret_id/version`，不保存 secret。不同 namespace 用于 person、visit、date offset，避免 token 复用。

这是 pseudonymisation，不应夸称为不可逆匿名化。虽然数据是 synthetic，公开输出仍不应含 raw Patient_No、Case_No、原始精确日期、ward/department 等非必要 quasi-identifiers。

#### 2.2 日期规则

采用每患者一个确定性的“整日历年偏移”：

`year_delta = deterministic_secret_function(Patient_No)`

将同一 delta 用于：

- `Patient_DOB` year；
- `Death_Date` year；
- visit start/end/planned dates；
- lab result datetime；
- medication order datetime；
- surgical date；
- derived observation/observation-period dates。

这样患者的 birth-event、event-death 年龄关系保持，所有表间顺序和小时差通常不变。遇到 29 February 映射到非闰年时使用固定 fallback（例如 28 February）并记录 exception；测试允许这一个明确规则。

不使用“每表不同偏移”，也不单独随机化 time-of-day。日期平移会破坏真实 calendar-year trend，因此报告必须声明该 CDM 不适合季节或年份流行病学分析。

---

### 3. Athena vocabulary mapping process and mapping-sheet schema

当前已核验 Athena 对脚本返回 HTTP 403，所以计划不能声称任何 concept ID 已验证。执行期可用人工 Athena browser、课程提供的本地 vocabulary tables 或 Usagi。

#### 3.1 工作流

1. 按 domain 生成 distinct source-term 文件并附 frequency：
   - diagnosis：72 distinct；
   - lab：64 distinct `(Test_Code, Short_Text)`；
   - drug：73 cluster codes；
   - procedure：6 codes；
   - demographics、visit/type、qualitative result、unit 分开。
2. 先确认 source vocabulary：
   - diagnosis 是否 ICD-10-AM：未确认；
   - surgical 是否 TOSP：未确认；
   - local lab/drug codes：当前按 local vocabulary。
3. 若 source vocabulary 已在 OMOP vocabulary：
   - 查 `CONCEPT`；
   - 用 `CONCEPT_RELATIONSHIP.relationship_id='Maps to'`；
   - 校验 active、Standard、target domain。
4. 不支持的 local codes 用 Usagi/人工搜索；只接受人工批准结果。
5. 按 frequency 排序审核，映射 distinct term 一次，不逐行搜索 366 条数据。
6. 锁定 vocabulary version 后冻结 mapping snapshot；更新 vocabulary 时重新验证。

候选优先方向但不是既定结论：

- diagnosis → Standard Condition/Observation concepts；
- labs → Standard Measurement concepts，常见候选 vocabulary 为 LOINC；
- drugs → Standard Drug concepts，常见候选为 RxNorm/RxNorm Extension；
- procedures → Standard Procedure concepts；
- units → Standard Unit concepts。

每项均需在实际 Athena/vocabulary snapshot 核验。

#### 3.2 Mapping sheet schema

建议一条 source-to-target edge 一行：

| Column | 含义 |
|---|---|
| `mapping_group_id` | 一对多映射的共同组号 |
| `domain_workstream` | condition/measurement/drug/procedure/visit/demographic/value/type |
| `source_table`、`source_column` | 来源位置 |
| `source_vocabulary_id_candidate` | `LOCAL_LAB`、`LOCAL_DRUG`、`ICD10AM?` 等 |
| `source_code`、`source_description` | 原始 code/text |
| `context_json` | chapter、form、strength、component type 等 |
| `frequency` | source occurrence count |
| `target_concept_id` | Athena 核验后填写 |
| `target_concept_name`、`target_vocabulary_id` | 审核信息 |
| `target_domain_id` | 决定 OMOP table |
| `standard_concept`、`valid_start/end`、`invalid_reason` | vocabulary validation |
| `relationship` | `Maps to` / `Maps to value` / manual equivalent |
| `map_sequence` | 一对多序号 |
| `status` | `UNREVIEWED/SUGGESTED/APPROVED/REJECTED/NO_MATCH/NEEDS_CLINICAL_REVIEW` |
| `reviewer`、`review_date`、`rationale` | 审核证据 |
| `vocabulary_version` | 可复现性 |
| `mapping_method` | local SQL/Athena/Usagi/manual |
| `issue_id` | unresolved issue reference |

ETL 只使用 `APPROVED` mapping。

#### 3.3 Failed 与 one-to-many

- target domain 已知但无匹配：required `*_concept_id` 使用 OMOP 无匹配占位值，并保留 `*_source_value`；该占位需在交付 vocabulary 中再次核验。
- domain 也不确定：不强行装表，进入 quarantine。
- 多个 `Maps to`：生成多条 target event，每条保持相同 source lineage。
- `Maps to value`：通常生成一个 attribute event，并将 value concept 写入 `value_as_concept_id`，不是无条件生成第二个 event。
- 所有一对多结果必须人工判断是否为真正拆分，而非模糊匹配。

---

### 4. OMOP CDM target tables and field specification

仅输出原计划的 8 个 clinical tables，不足以宣称是完整的 OMOP CDM instance。建议课程交付生成 10 个非空/相关表；若装载数据库，还应使用完整 v5.4 DDL，未使用表可以为空。

| Table | Required fields 本项目填法 |
|---|---|
| `PERSON` | `person_id`、`gender_concept_id`、`year_of_birth`、`race_concept_id`、`ethnicity_concept_id` 均 Required=TRUE；source values 可选。[CDM v5.4 PERSON] |
| `DEATH` | `person_id`、`death_date` Required=TRUE；death type 可选但建议在 provenance 确认后填写。[CDM v5.4 DEATH] |
| `VISIT_OCCURRENCE` | ID、person、visit concept、start/end date、visit type 均 Required=TRUE。[CDM v5.4 VISIT_OCCURRENCE] |
| `CONDITION_OCCURRENCE` | ID、person、condition concept、start date、condition type Required=TRUE；visit FK optional。[CDM v5.4 CONDITION_OCCURRENCE] |
| `DRUG_EXPOSURE` | ID、person、drug concept、start/end date、drug type Required=TRUE。[CDM v5.4 DRUG_EXPOSURE] |
| `PROCEDURE_OCCURRENCE` | ID、person、procedure concept、procedure date、procedure type Required=TRUE。[CDM v5.4 PROCEDURE_OCCURRENCE] |
| `MEASUREMENT` | ID、person、measurement concept、date、measurement type Required=TRUE。[CDM v5.4 MEASUREMENT] |
| `OBSERVATION` | ID、person、observation concept、date、observation type Required=TRUE。[CDM v5.4 OBSERVATION] |
| `OBSERVATION_PERIOD` | ID、person、start/end、period type 全部 Required=TRUE；每人至少一条。[CDM v5.4 OBSERVATION_PERIOD ETL convention] |
| `CDM_SOURCE` | source name、abbreviation、holder、source/CDM release dates、CDM version concept、vocabulary version 等必填字段。[CDM v5.4 CDM_SOURCE] |

`OBSERVATION_PERIOD` 每人一条，以最早至最晚有效 clinical event 构造，不以 death 延长。必须标记为“从 event span 推导”，不能声称此区间内没有记录就表示没有疾病。[`OBSERVATION_PERIOD` table/user guide]

所有 Type Concept 必须在同一 vocabulary snapshot 中核验，包括：

- inferred observation period；
- source-supplied encounter；
- diagnosis provenance；
- medication order/prescription；
- procedure record；
- laboratory result；
- demographic observation；
- CDM version concept。

当前不提供任何具体 ID。

主键由中央 allocator 在 normalized staging 完成后按稳定 source lineage 排序分配。每张表可从 1 连续编号；表间主键不要求全局唯一，因此不让六人各占随意 key range。所有 FK 在最终写出前统一解析。

输出约定：

- CDM v5.4 官方 column order；
- UTF-8、RFC 4180 CSV；
- 日期 `YYYY-MM-DD`；
- datetime `YYYY-MM-DD HH:MM:SS`；
- NULL 使用统一显式 token，如 `\N`；
- concept/key 字段为整数，不带 `.0`；
- vocabulary version、mapping commit、input file hashes 写入 release manifest。

---

### 5. Python ETL module architecture

只规划接口，不在本阶段实现：

```text
discover_inputs(config) -> input_manifest
profile_and_validate(manifest) -> verified_staging
normalize_sources(staging) -> normalized_tables
build_identity_registry(normalized, secret) -> registries
apply_patient_date_shift(normalized, registries, secret) -> deidentified_staging
load_approved_mappings(mapping_snapshot) -> mapping_index
transform_<domain>(...) -> cdm_table + lineage + issues
allocate_keys(all_tables) -> keyed_cdm
run_quality_gates(keyed_cdm, lineage) -> validation_report
write_release(keyed_cdm, manifest) -> reproducible_package
```

模块边界：

- `io_manifest`: 25 files、sheet/column contract、checksums；
- `source_contracts`: verified schema、dtype、row counts；
- `identity`: person/visit registry、HMAC；
- `dates`: year-offset、leap-day rule；
- `normalize`: dedup visit、explode diagnoses、result parser；
- `vocabulary`: mapping-sheet loader、standard/domain/validity checks；
- `transforms`: 每个 OMOP table 独立纯函数；
- `keys_lineage`: deterministic PK、source-row-to-target trace；
- `dq`: structural、linkage、temporal、semantic tests；
- `release`: CDM files、quarantine、mapping snapshot、run manifest。

配置中固定 CDM version、column order、delimiter、NULL、date formats、source release date、vocabulary version 和 Type Concept mapping。缺少 required concept/type 或 source release metadata时应 fail closed，而不是现场猜值。

---

### 6. 6-person parallel development and integration strategy

| 成员 | 主责 | 强制交付 |
|---|---|---|
| 1：Integration/identity lead | contracts、central IDs、date shift、PERSON、DEATH、OBSERVATION_PERIOD、CDM_SOURCE | registry、schema contract、release manifest |
| 2：Visit/condition | visit dedup、VISIT_OCCURRENCE、diagnosis explode、diagnosis mapping | visit/condition spec 与 tests |
| 3：Lab terminology | 64 lab tests、qualitative values、operator mapping审核 | approved mapping snapshot |
| 4：Measurement ETL/QA | numeric parser、MEASUREMENT、lab lineage和DQ | 162-row reconciliation |
| 5：Drug terminology | 73 cluster codes、combination products、form/strength review | drug mapping snapshot |
| 6：Drug/procedure ETL | DRUG_EXPOSURE、7 surgeries、procedure mapping、release-level clinical review | drug/procedure tables与tests |

集成规则：

- 成员 1 是唯一 ID/date/key authority；
- mapping reviewer 不应是唯一 mapping author；
- 3↔4、5↔6 互审；2 审核 surgical domain；1 执行最终 FK 和 schema gate；
- 每个 PR/交付单元必须包含 source-to-target spec、mapping delta、row reconciliation、tests；
- 不允许成员直接编辑最终 CDM CSV；最终文件只能由统一 pipeline 生成。

APGAR 是独立 workstream。可由一名成员在 ETL code freeze 后担任编辑、另一人快速复核；必须修正“用 Apgar 决定是否开始复苏”的错误表述，但不纳入 OMOP ETL acceptance criteria。

---

### 7. Automated tests and quality validation

#### 7.1 Source contract

- 正好 25 个 workbook、每类 5 个、只读 `Sheet1`；
- raw row count：5 + 22 + 162 + 170 + 7 = 366；
- column sets 与已核验 profiling 完全一致；
- distinct patients=5；
- 未知 Patient_No、Case_No ownership mismatch 均为 0。

#### 7.2 Row reconciliation

确定性基线：

- `PERSON=5`
- `DEATH=2`
- `VISIT_OCCURRENCE=21`
- `MEASUREMENT=162`，除非明确批准的一对多 test mapping
- `PROCEDURE_OCCURRENCE=7`
- `OBSERVATION_PERIOD=5`
- `CDM_SOURCE=1`

`CONDITION_OCCURRENCE` 不能硬编码为 159，因为 159 包含 duplicate visit 的 diagnosis occurrences，且 domain routing/一对多可能改变目标条数。应验证：

`source diagnosis candidates after visit dedup = Condition rows + other-domain rows + quarantined rows`，再解释一对多 expansion。

`DRUG_EXPOSURE` 同理：

`170 source components = mapped groups + no-match groups + quarantined groups`，目标行数再加批准的一对多 expansion。

#### 7.3 CDM structural checks

- 所有 Required=TRUE 字段非 NULL；
- PK 唯一、正整数；
- 所有 person FK 存在；
- visit FK 存在且 event.person_id 等于 visit.person_id；
- concept target 为 active Standard concept，domain 与 table 相符；
- source concept 只有在 exact supported vocabulary match 时填写；
- column order、types、length constraints 符合 v5.4。

#### 7.4 Temporal/linkage checks

- visit start ≤ end；
- 同一患者 visits 不 overlap；
- 同患者所有表使用相同 year delta；
- 日期平移前后事件顺序保持；
- birth year ≤ 所有 event year；
- 两名 deceased patient 的 death_date 晚于最后 event；
- 20 条 pre-admission medication 仍为 20 条预期 exception，小时差保持；
- lab 的 162 个 visit FK 均 NULL，除非未来获得明确 episode semantics；
- 7 个 surgery 均链接正确 visit，但 procedure datetime 默认 NULL。

#### 7.5 Clinical semantics

- primary/secondary diagnosis 分开并保留 status；
- secondary list count 与 `No_of_Secondary_Diagnosis_Subvention` 一致；
- `<2.0` 被解析为 operator + numeric value；
- qualitative lab 不进入 `value_as_number`；
- 所有 lab unit 均 NULL，不从 reference range 猜测；
- insulin corrupted dose 不进入 quantity；
- Norepinephrine range 不进入 quantity；
- medication `drug_type` 表示 order，不表示 administration；
- no route/frequency/duration/administration 被推造；
- `Operation_Table_Code` 未经确认不进入 modifier；
- `No Mapping` 不被映射成 Buddhism、Married 或其他已知类别。

#### 7.6 人工 review gates

自动化适合：读取、合并、dedup、ID/date、一对多展开、numeric parsing、mapping application、FK/domain/row-count tests。

必须人工审核：ICD vocabulary 身份、Visit concept、Type Concept、所有 clinical mapping、组合药物、qualitative values、Religion/Marital concepts、TOSP、lab units/episode、手术时间、insulin dose、模糊及一对多映射。

---

### 8. Schedule and main risks

课程 deadline 未提供，以下是可压缩的 10 个工作日相对计划，而非已知期限。

| 日程 | 工作 |
|---|---|
| Day 1 | 冻结 source contracts、CDM v5.4、ID/date/output conventions |
| Day 2 | normalized staging、visit dedup、distinct mapping extracts |
| Day 3–5 | 四个 domain mapping；高频项优先，人工复核 |
| Day 4–6 | 六人并行完成 table-level ETL design/tests |
| Day 7 | 第一次 integration、FK/domain/row reconciliation |
| Day 8 | 解决 lab、drug、visit、procedure semantic issues |
| Day 9 | full validation、lineage抽样、重复运行一致性 |
| Day 10 | 冻结 mapping/vocabulary version、生成报告与提交包 |

主要风险：

1. **Athena/词表访问**：脚本访问已知 403；准备人工 browser 或课程提供的本地 vocabulary/Usagi。
2. **ICD-10-AM 未确认**：错误选择 ICD10/ICD10CM 会造成错误映射；在 source vocabulary gate 前不批准诊断 mapping。
3. **lab 无单位且 episode 未链接**：不推断单位、不虚构 visit；降低分析精度但保护语义。
4. **orders 被误当 administration**：用 Type Concept 和报告明确区分。
5. **TOSP 与 operation time 不确定**：文本人工映射，datetime 默认 NULL。
6. **小样本 quasi-identification**：输出不含 raw IDs/原日期/不必要 ward 文本；说明只是 pseudonymised synthetic dataset。
7. **人工映射一致性**：统一 sheet、双人审核、固定 vocabulary version。
8. **范围膨胀**：不为 5 位患者建立无 source 支持的 provider/care_site/visit_detail 等结构。

---

### 9. Answers to the focus questions

1. **只输出 8 张表是否足够？**  
   不足以称为完整 OMOP CDM instance。课程级 clinical extract 至少再加入 `OBSERVATION_PERIOD` 和 `CDM_SOURCE`，形成 10 张相关表；正式数据库还应使用完整 v5.4 DDL，并依赖可解析 concept ID 的 vocabulary snapshot。

2. **是否需要 `OBSERVATION_PERIOD`？**  
   需要。v5.4 ETL convention 要求每个 Person 至少一条。每人用最早至最晚 clinical event 推导一条，并明确这不证明期间内所有事件均被完整捕获。

3. **如何保证同一患者在五类 source 中 ID 一致？**  
   所有表只连接唯一中央 `person_registry`；禁止各成员单独编号。registry 由 HMAC pseudonym 和稳定整数 `person_id` 构成，并验证所有 FK 的 patient ownership。

4. **日期平移会破坏 birth/visit/lab 时间关系吗？**  
   同一患者所有年份与 datetime 使用同一个整日历年偏移，所以年龄关系、先后次序和大多数时间差保持。仅 leap-day fallback 是明确例外并自动测试。

5. **一个 visit 多个 diagnosis 如何正确拆分？**  
   一个 deduplicated Case_No 对应一个 visit；primary 生成一条 candidate，secondary comma-list 每个元素生成一条；保留 primary/secondary status，并按标准 concept 的 domain 路由。

6. **如何区分 medication order 与实际 administration？**  
   source 只有 order，没有 MAR。写入 `DRUG_EXPOSURE` 是因为该表允许 prescription/order records，但 `drug_type_concept_id` 必须选择 order/prescription provenance，绝不能使用 administration 类型；报告也明确不代表实际给药。

7. **lab numeric、qualitative 与 units 如何映射？**  
   数值进入 `value_as_number`；`<2.0` 分成 operator 与 number；qualitative result 经审核进入 `value_as_concept_id`，原文进入 `value_source_value`；source 无 unit，因此 unit 字段全部 NULL，不推断。

8. **Religion 和 Marital Status 放哪里？**  
   放 `OBSERVATION`。由于 source 无记录日期，默认使用明确标注的 earliest-event proxy；若课程不接受代理日期，则保留 staging 而不生成不合规 observation。

9. **失败或一对多 vocabulary mapping 如何处理？**  
   domain 已知但无匹配时使用无匹配占位并保留 source value；domain 不明则 quarantine。多个 `Maps to` 生成多条 event；`Maps to value` 写入 value concept。所有一对多必须人工批准。

10. **怎样减少重复手工 Athena 搜索？**  
    先提取 distinct codes/text 和 frequency，按 domain 批量处理；支持的 vocabulary 用本地 `CONCEPT`/`CONCEPT_RELATIONSHIP` 查 `Maps to`；local terms 用 Usagi；每个 distinct key 只审核一次，并固定 mapping snapshot。

11. **哪些应自动化，哪些必须人工审核？**  
    合并、dedup、ID/date、解析、mapping application、key/FK、domain validation、row reconciliation 和报告应自动化。词表身份、clinical concept、visit/type、qualitative value、TOSP、组合药、一对多语义、损坏 dose、lab episode/unit 和手术时间必须人工审核。

---

# Round 1 · A 对 B 的挑战（含 A 的自我修正）

<!-- source: debate/r1_claude.md -->

## Architect A：Round 1 对 Architect B 方案的问题清单

**标记**：【V】= facts §4 的 profiling 结果或 CDM v5.4 extract 原文；【H】= 假设，附确认方法。本轮没有访问 Athena，文中不引用任何 concept ID。

---

### 一、B 方案的问题

#### B1【major】按整年平移日期，去标识强度不足，而且闰日回退在本数据中一定会触发

**证据**
- **去标识强度**：facts §4.1【V】把"exact timestamps"列为准标识符。B 的方案只改年份，月、日、时、分全部原样保留。例如 `2016-02-09 23:07` 平移后变成 `20XX-02-09 23:07`。知道某次入院月日和时刻的人可以直接对上记录。year_delta 的取值范围 B 也没有给出。
- **闰日问题**：profiling【V】显示 Patient-4 的 visit `Case-4-04` 的 Dis_DateTime 是 **2016-02-29 15:48**。只要 year_delta 不是 4 的倍数，就会回退到 02-28。结果有两个：
  - 该 visit 的 LOS 少 1 天，和 B 自己在 §7.4 写的"小时差保持"断言、以及用 LOS 验证 Dis−Adm 的规则直接冲突。
  - 如果同一患者在 02-28 15:48 之后还有事件，先后顺序会颠倒（【H】。确认方法：检查 med 的第 5 个 Case_No 是否就是 Case-4-04）。
- B 的表述是"测试允许这一个例外"。这其实是在用测试例外掩盖规则本身的缺陷。

**修正**：改为按天平移。
- 每位患者 d = 7·k 天，|d| ∈ [7, 364]，所有 datetime 加同一个 d。这样间隔、顺序、星期几都不变，也不存在闰日问题。
- 只有年份的字段（出生、死亡）用 Δy = round(d/365.25) 平移。
- 如果组内坚持保留"年"的语义，可以退而用 d = 364·k 天，同样没有闰日问题，但月日只被扰动 k 天，去标识强度仍然弱，需要在报告中写明。

#### B2【major】domain 不确定的行进入 quarantine，会从 CDM 中丢失源记录

**证据**
- CONDITION_OCCURRENCE 的 User Guide 写明："Record all conditions as they exist in the source data."
- Book of OHDSI 写明："It is okay to map some codes to CONCEPT_ID = 0"。
- 映射失败的码没有 target concept，domain 自然无从确定。按 B 的规则，这些行会被移出输出。最可能受影响的是 AM 特有码和外因码（U739、Y9222、M85503 等【V】）。B 的对账公式把 quarantine 也算进去，所以对账照样通过，数据丢失不会被发现。

**修正**：未映射的码写 concept_id = 0，按源字段写入默认表（诊断→CONDITION，实验室→MEASUREMENT，药物→DRUG，手术→PROCEDURE），保留 *_source_value，同时列入未映射清单。quarantine 只用于解析失败的行，例如 Excel 损坏的值。

#### B3【major，按现方案无法执行】诊断映射被 ICD-10-AM gate 卡住，没有回退方案，也没有处理码的格式

**证据**
- B 写的是"在 source vocabulary gate 前不批准诊断 mapping"，但没有说明 gate 不通过时怎么办。诊断有 72 个码，是映射工作的关键路径。
- 源码不带小数点【V】（`I214`、`I2511`、`E1472`）。ICD10 和 ICD10CM 在 CONCEPT 表中的 concept_code 通常带小数点（【H】。确认方法：下载 vocabulary 后在本地 CONCEPT 表抽查）。B 第 3 步写的"查 CONCEPT"如果直接拿源码精确匹配，大部分会落空。
- 5 位和 6 位码共 11 个【V】，很可能带有 AM 扩展位，WHO ICD10 中没有对应码。

**修正**：
1. 对码做规范化：第 3 位之后插入小数点。
2. 先在 ICD10（WHO）中精确匹配；匹配不到就截到 4 位，并标 equivalence=WIDER；仍匹配不到的转人工。
3. 把 gate 改成有时限的检查（例如 Day 2 前确认 ICD10AM 是否存在），不再作为阻塞条件。

#### B4【major】Dosage_Ordered 被整列丢弃，同时把 Order_Text 写进 sig，语义错误

**证据**
- extract 中 sig 的定义是："verbatim instruction for the drug as written by the provider"。而 Order_Text 的实际值【V】是药名，例如 "Dulcolax [Bisacodyl]"、"Harnal OCAS [Tamsulosin…]"，不是给药指令。
- B 保留了 dose_unit_source_value，却把剂量数值只放在 audit 里。输出中只有单位没有数值，这个字段就失去了意义。
- DRUG_EXPOSURE 的 ETL convention 写明："it is important for the ETL to provide as much information as possible from the data"。

**修正**：
- quantity 保持 NULL（这一点采纳 B 的意见，见 §三）。
- sig 写源数据中的原值组合 `"<Dosage_Ordered> <Dosage_Ordered_Unit>"`，例如 "10 mg"、"0 - 2 mcg/kg/min"。Insulin 的损坏单元格写 NULL 并记入 dq_log。
- Order_Text 只作为映射时的辅助信息。品牌名有助于选到 Branded Drug。

#### B5【minor】lab 的 visit FK 全部置 NULL，但没有说明为什么不采用 CDM 的"日期包含"规则，episode 分组信息也没有保留下来

**证据**
- MEASUREMENT.visit_occurrence_id 的 ETL convention 写明："If a MEASUREMENT_DATE occurs within the start and end date of a Visit it is a valid ETL choice to choose the VISIT_OCCURRENCE_ID … an attempt should be made to locate"。
- 有 2/162 行落在住院窗口内【V】。B 没有解释为什么不用这条规则。
- lab Case_No 是源数据提供的 episode 标识【V】，并不是虚构的。B 把它放进 lineage sidecar，而 sidecar 不对外共享，分组信息实际上就丢了。

**修正**：
- 如果采用置 NULL 的方案，要在文档中写明理由：这 2 行属于一个跨越入院时刻的 episode，按日期挂到住院上会把同一个 episode 拆开。
- 在可共享的 lineage 中保留伪名化的 episode token。
- 是单独建 episode visit 还是置 NULL，留到 Round 2 由组内决定（我方案的缺点见 A3）。

#### B6【minor】MEASUREMENT=162 的硬性基线和 B 自己的 domain 路由原则矛盾

**证据**：MEASUREMENT 的 ETL convention 写明："Only records where the source value maps to a Concept in the measurement domain should be included"。"Slide / Reviewed"、"Lipaemic Index" 有可能落到其他 domain（【H】，以 Athena 结果为准）。

**修正**：对账改为 162 = MEASUREMENT 行数 + 路由到其他表的行数 + concept=0 的行数，再加上一对多展开的数量。

#### B7【minor】NULL 用 `\N` 表示，与 B 自己选的 RFC 4180 CSV 不一致

**证据**：`\N` 是 PostgreSQL / MySQL 文本 COPY 格式的约定。PostgreSQL 的 CSV 模式默认把未加引号的空串当作 NULL；按默认设置加载时，varchar 列中的 `\N` 会被读成字面字符串。

**修正**：NULL 用空字符串，并写进接口契约。

#### B8【minor，无法执行】缺少 source release metadata 时 "fail closed"

**证据**
- source_release_date 是 Required 字段，而它的真实值未知【V §4.4】。按 B 的规则，pipeline 会直接停止。
- 如果改填源数据的最晚事件日期（2016-12-17，未平移），又会泄露平移量。
- extract 写明："In some systems that is the same as the date the ETL was run"。

**修正**：source_release_date 填 ETL 运行日期。

#### B9【major，计划层面】分工负载失衡，关键岗位缺少负责人

**证据**
- 成员 2 一个人承担了 visit 去重、visit_concept 规则、diagnosis 拆分，以及 72 个诊断码的映射和 domain 路由，这是全项目最重的一块，也是关键路径。
- 实验室（64 项）和药物（73 项）各配了 2 个人。
- Athena vocabulary 的下载和快照没有指定负责人。
- APGAR 放在"ETL code freeze 之后"，也没有点名由谁负责。这一处修正只涉及一句话，拖到最后反而会和截止日期冲突。

**修正**：
- visit 和 condition 分给两个人。
- 诊断映射指定交叉审核人。
- 由集成负责人在 Day 1 完成 vocabulary 下载。
- 第一周点名 APGAR 负责人。

#### B10【minor】visit_concept_id 只有"无匹配占位"的兜底，没有给出决策规则

**证据**
- visit_concept_id 是 Required 字段，extract 要求 "should be standard and belong to the Visit domain"。
- 源数据中的组合只有 Adm_Type_Desc 2 种 × Referral 2 种【V】，规模很小，完全可以决定。
- 如果 21 个 visit 全部填 0，基于 Inpatient 或 ER 的分析就做不了。

**修正**：在接口契约中写一张不超过 4 行的规则表，Day 2 前由人工批准。

#### B11【minor】评阅者无法复现

**证据**：secret 只存在于 environment 中，评阅者拿不到，也就无法重跑 pipeline。

**修正**：随交付物附一个 `demo_secret`，生成的结构相同，ID 和偏移量不同。

---

### 二、对比后发现的我方（A）问题

| # | 严重度 | 问题 | 修正 |
|---|---|---|---|
| A1 | major | 我把单次医嘱剂量写进 quantity。extract 写明 "If liquid, quantity stands for the total amount dispensed or ordered"，语义不符 | quantity 置 NULL，剂量写入 sig（同 B4） |
| A2 | major | route_source_value 写的是 Dosage_Form，并"由剂型推断"。extract 要求它 "houses the verbatim value from the source data representing the drug route"，而源数据没有 route【V】 | route 两个字段都置 NULL。剂型只作为映射时的辅助信息 |
| A3 | minor | 为 5 个 lab episode 建 visit 时，visit_concept 和 end_datetime 都是推测的，并且有 2 个 episode 没有对应入院 | 降级为 Round 2 的待决项，与 B5 合并讨论 |
| A4 | minor | 我按"来源模块 × 表"划分 ID 段，理由是方便并行。但 B 提出的中央 allocator 已经能避免冲突，分段的意义不大 | 改用中央 allocator，每张表从 1 开始连续编号 |

---

### 三、B 做得比我好、我准备采纳的地方

1. quantity 不填单次剂量；不根据剂型推断 route（对应 A1、A2）。
2. 只有年份的字段与 datetime 使用完全相同的年偏移，没有我方 Δy 取整带来的 ±1 年误差。前提是 B1 指出的去标识和闰日问题得到解决。
3. 增加 source contract 测试：25 个文件、各类表的列集合、总行数 366。
4. mapping sheet 增加 `valid_start/end`、`invalid_reason`、`mapping_method`、`issue_id` 等列，用于检查 concept 的有效性。
5. 条件对账不写死 159，因为 159 包含重复 visit 的诊断；按去重后的候选数来推。
6. 明确写出"这是 pseudonymisation，不是 anonymisation"；Religion 和 Marital 的代理日期如果不被课程接受，就留在 staging，不生成记录。
7. 不根据数值推断 HbA1c 的单位。我会把"用推断单位来选 LOINC"降级为【H】，并要求审核人签字确认。

---

# Round 1 · B 对 A 的挑战（含 B 认可 A 之处）

<!-- source: debate/r1_codex.md -->

以下问题均基于已核验 profiling 和所给 CDM v5.4 extract；没有假定任何 Athena 查询结果。

#### 对 Architect A 的主要问题

**B1 — Critical：凭空创建 5 个 lab visits**

- 证据：已核验事实仅表明 lab `Case_No` 与 `case_visit` 完全不匹配；其含义仍未知。A 却由 lab 时间范围构造 `VISIT_OCCURRENCE`，并推测为 ER/Outpatient。
- 规范：`VISIT_OCCURRENCE` 表示患者与医疗系统的一次真实 interaction；`visit_occurrence_id` 应对应“each unique interaction”。
- 问题：一个 lab episode identifier 不足以证明存在独立 visit，更不能由“同日入院前”推出 ER。
- 修复：162 条 `MEASUREMENT.visit_occurrence_id=NULL`；lab `Case_No` 只保存在受控 lineage。只有数据所有者确认其 encounter 语义后才创建 visit。

**B2 — Major：Visit 和 discharge 规则包含未经支持的临床推断**

- `Emergency + Intra-Hosp A&E → Emergency Room and Inpatient Visit` 未由源数据证明；`Referral_Type_From` 表示来源，不一定表示同一个 ER encounter。
- `"Pat discharged"` 和 `"Followup at SOC"` 也不能自动解释为 discharged to Home。
- 规范：`visit_concept_id` 必须是实际 visit kind 的 Standard Visit concept；`discharged_to_*` 表示患者去向。
- 修复：先列出全部 source combinations，由人工审核；无法确定时 concept 使用无匹配值并保留 source value。不要把 `"Pat discharged"` 自动映射为 Home。

**B3 — Critical：自动截短 ICD code 是危险的错误映射**

- A 建议精确匹配失败后把 `I25.11` 截为 `I25.1` 并标为 WIDER。
- 规范：`Maps to` 是从已识别的 source concept 到 Standard concept 的关系；不能通过字符串截断冒充词表关系。
- 已核验限制：诊断可能是 ICD-10-AM，但 source vocabulary 尚未确认。
- 修复：先确认 ICD-10-AM/ICD10/其他版本；只对 exact source concept 使用正式 `Maps to`。更宽泛概念只能作为明确的人工 mapping，记录理由并双人审核，不得自动批准。

**B4 — Major：domain 未知时仍强塞入“默认表”违反 domain routing 约束**

- A 提议所有 `UNMAPPABLE` 诊断默认进入 CONDITION、lab 进入 MEASUREMENT 等。
- 规范明确说：
  - `CONDITION_OCCURRENCE` 只接收映射到 Condition domain 的记录；
  - `MEASUREMENT` 只接收映射到 Measurement domain 的记录；
  - `DRUG_EXPOSURE`、`PROCEDURE_OCCURRENCE` 同理。
- 修复：只有 domain 已确认、但无 Standard target 时才可在对应表使用 concept 0。连 domain 都不确定的记录应 quarantine，并纳入行数对账。

**B5 — Major：在无单位情况下用“推断单位”选择 LOINC**

- A 断言 `GHB=5.8` 是 `%`、`GHB2=40` 是 `mmol/mol`、Creatinine 80 是 `µmol/L`。
- 已核验事实：lab 没有 unit column；这些均是推测。
- 规范：source 无 unit 时，`MEASUREMENT.unit_concept_id=NULL`。不同单位、specimen、method 可能对应不同 Measurement concepts。
- 修复：不能把数值范围或参考区间推断出的单位作为 mapping 事实。选择不依赖未知属性、且语义仍成立的 concept；否则标为 `NEEDS_CLINICAL_REVIEW` 或不批准。

**B6 — Major：把单次剂量写入 `DRUG_EXPOSURE.quantity`**

- A 明知 `Dosage_Ordered` 是单次剂量而非总量，仍计划写入 `quantity`。
- 规范：`quantity` 表示 ordered/dispensed product amount，并需与 `DRUG_STRENGTH` 的单位语义一致；它不是通用 dose 字段。
- 修复：本数据缺少总量、频次和疗程，`quantity=NULL`。原始剂量及单位保留在 lineage/audit；不能为了保存字段而改变其语义。

**B7 — Major：由 Dosage_Form 推断 route，并伪装成 route source**

- 已核验事实：没有 route column。
- A 建议 Tablet→oral、Cream→topical，并把 `Dosage_Form` 写入 `route_source_value`。
- 规范：`route_source_value` 应保存源数据中的给药途径；`route_concept_id` 是该 source route 的映射。
- 问题：dosage form 不是 route；即使常见关联合理，也不是源记录的给药途径。
- 修复：`route_concept_id=NULL`、`route_source_value=NULL`；`Dosage_Form` 仅作为药物产品 mapping context。

**B8 — Major：把全部 MED/FLD/DIL 组分强制视为 Drug**

- 数据含 Fresh Frozen Plasma、营养品、护肤品、diluent 等，不保证全部映射到 Drug domain。
- 规范：只有 Standard target domain=`Drug` 的记录才能进入 `DRUG_EXPOSURE`。
- 修复：每个 component 经 approved target domain 检查；非 Drug domain 路由到合适表或 quarantine。不能仅凭源表名称或 `Component_Type_Code` 决定目标 domain。

**B9 — Major：日期规则并非真正的“患者级统一平移”**

- 精确 datetime 加 `d` 天，而出生/死亡年份加 `round(d/365.25)` 年；这是两种不同转换。
- 因此“出生—事件—死亡关系保持”的表述过强，特别是在事件跨年时，按年份计算的年龄可能发生额外变化。
- 此外偏移只有 104 种、保持星期和 time-of-day，去标识强度较弱；应称 pseudonymisation。
- 修复：采用一个明确的 calendar-year offset 应用于所有 year/date/datetime，或明确承认双规则及其误差并测试所有边界。扩大 offset 空间，不必刻意保留星期。

**B10 — Major：Religion/Marital 的 observation date 是伪造语义**

- A 使用 `OBSERVATION_PERIOD` 起点作为 `observation_date`。
- 规范：`OBSERVATION.observation_date` 是 observation “was obtained”的日期，且 Required=TRUE。
- 最早 clinical event 与人口学资料采集时间没有已验证关系。
- 修复：若教师接受 proxy，必须明确标为 derived proxy；更稳妥方案是保留 normalized staging，不生成 OBSERVATION，直到获得采集日期或明确课程约定。

**B11 — Major：`CDM_SOURCE.source_release_date` 填 ETL 运行日不符合字段语义**

- A 写：`source_release_date = ETL 运行日`。
- 规范：这是“date the data was extracted from the source system”；`cdm_release_date` 才是 ETL 完成日期。
- 修复：从课程交付信息、文件元数据或数据提供者取得 extract date。若确实未知，不能无说明地替换为 ETL 日；应记录缺口并向课程方确认。

**B12 — Major：删除同 visit 内主次重复 diagnosis 会丢失 provenance**

- A 提议如果同一码同时为 primary 和 secondary，只保留 Primary。
- 规范：应记录 source 中存在的所有 condition instances；同 visit 的重复 condition 可以保留，各有唯一 `condition_occurrence_id`。
- 修复：主、次诊断分别保留，因为 status 和 source column 不同。只有已经确认的整行 source duplicate 才去重。

**B13 — Major：Type Concept 的来源判定过于笼统**

- A 多处先固定 `"EHR"`，但 primary diagnosis 字段名含 `Mediclaim`，secondary 来自 `Subvention`；death、procedure 等具体 provenance 也未确认。
- 规范：各 `*_type_concept_id` 必须反映记录来源，如 EHR、claim、order、lab result。
- 修复：按 source table/column 建立独立 Type Concept mapping；在 provenance 未确认前不得统一写 EHR。所有具体 ID 均须在 Athena 核验。

**B14 — Major：把“10 张表”称为 CDM v5.4 产出不够准确**

- `*_concept_id` 依赖 `CONCEPT` 等 vocabulary/reference tables。只有 10 张 clinical CSV 不能独立构成可查询、可验证的完整 CDM database。
- 修复：明确交付是“10-table OMOP-aligned clinical extract”；若声称建立完整 CDM instance，则使用完整 v5.4 DDL并加载对应 vocabulary snapshot，未使用 clinical tables 可为空。

**B15 — Major：mapping approval 没有强制 active-concept 验证**

- Mapping sheet 缺少 `valid_start_date`、`valid_end_date`、`invalid_reason`；测试只在“若有本地 CONCEPT 表”时检查 Standard/domain。
- Book of OHDSI 要求 target 是 active Standard concept；仅记录 `standard_concept='S'` 不足以证明仍有效。
- 修复：本地 vocabulary snapshot 或等效导出应成为 mandatory dependency；批准时验证 `standard_concept='S'`、正确 domain、`invalid_reason IS NULL`、有效期和 vocabulary version。

**B16 — Major：输入侧可复现性不足**

- A 的 manifest 只明确记录输出 hash、vocabulary version、git commit；没有强制记录 25 个输入文件的 SHA256、sheet、行数和 schema。
- 这会导致输入文件变化后无法证明是同一次 ETL。
- 修复：release manifest 加入全部 25 个文件的路径标识、SHA256、sheet、row count、column signature；source contract 断言每类正好 5 个文件且只有预期 `Sheet1`。

#### Architect A 做得比我更好的地方

- 明确发现了 Antibody Screen 长文本超过 `value_source_value varchar(50)` 的风险。其截断方案还应补充完整原文 lineage，但这个约束识别得很好。
- 给 mapping sheet 增加 `equivalence=EQUAL/WIDER/NARROWER/INEXACT`，比我的 schema 更能表达人工 mapping 的语义损失。
- 对精确 datetime 使用按天偏移，能严格保持 LOS、入院前用药小时差和事件间隔；这比我的 calendar-year shift 在闰日附近更精确，但需要修正与 year-only 字段不一致及偏移空间过小的问题。
- 对 exact duplicate 明确要求写入 `dq_log.csv`，审计性比仅做去重更好。
- CLI、stage1/stage2/stage3、dependency locking、每日全量集成和 PR/CI 规则更具体，可执行性更强。
- 把 APGAR 明确分配给 P2，并指出必须修正“用 Apgar 决定是否复苏”的错误，调度上比等 ETL freeze 后才处理更稳妥。
