# 01 · 需求与已核实事实（Phase 0）

状态：PLAN-ONLY，2026-10-22。所有结论都来自对原始文件的只读检查和官方规范原文。没有修改任何原始数据。

## 1. 作业要求（来源：小组规划 `BMI5207-Group3d.pdf`）

| # | 要求 | 来源 |
|---|---|---|
| R1 | 把 25 个文件（5 类 × 5 名患者）合并成 5 张表 | 小组规划 |
| R2 | 对每张表记录字段含义，并标出哪些字段是编码 | 小组规划 |
| R3 | 统一脱敏 patient_no、case_no 和日期，所有表使用同一种方法 | 小组规划 |
| R4 | 用 Athena 映射诊断、检验、药品、手术，以及性别、种族、宗教、婚姻状况 | 小组规划 |
| R5 | 用 Python 脚本转换成 OMOP CDM | 小组规划 |
| R6 | 验证完整性、临床语义和关联正确性，过程可重复执行 | Orchestrator 任务书 |
| R7 | APGAR 一页报告，单独交付 | 小组规划 + `Group_3d_assignment_write_up.pdf` |

**没有拿到**：课程官方 brief、评分标准、提交格式、截止日期。这是最高优先级的待确认项，见 [04](04-decisions-and-tradeoffs.md) U1。

## 2. 原始数据画像（已核实）

数据位置：`~/Downloads/Sample data for 5 patients_v2/Patient N <Patient_No>/<type>_patient N <Patient_No>.xlsx`。每个文件只有一个 `Sheet1`，同类文件的列完全一致。

| 源表 | 行数 | 列数 | 关键字段 | 需要映射的不同编码数 |
|---|---|---|---|---|
| patient demo | 5 | 8 | Patient_No、Patient_DOB（**只有年份**）、Gender、Race、Religion、Marital_Status、Deceased_Ind、Death_Date（**只有年份**） | Gender 2、Race 1、Religion 2、Marital 2 |
| case visit | 22（去重后 21） | 40 | Case_No、Adm/Dis_DateTime、Adm_Type_Desc、Referral_Type_From、Discharge_Type_Desc、Primary_Diagnosis_Code_Mediclaim、Secondary_Diagnosis_Codes_Subvention（逗号分隔，没有描述） | 诊断码 **72** 个；去重后共 **149** 条诊断候选 |
| lab results | 162 | 12 | Test_Code（本地码，4 个为空）、Short_Text、Test_Result（文本和数值混合）、Result_Test_Date、Min/Max_Range；**没有单位列** | **64** 个 (Test_Code, Short_Text) 组合 |
| medication order | 170 | 13 | Cluster_Preferred_Name_Code（本地码）及描述、Order_Creation_Date、Dosage_Ordered、单位、剂型、组分类型（MED 155 / FLD 8 / DIL 7）；**没有 route、频次、疗程、结束日期、给药记录** | **73** 个 |
| surgical | 7 | 6 | Surgical_Code（本地码，形式像新加坡 TOSP）、Surgical_Desc、Operation_Table_Code、operation_date | **6** 个 |

人工映射的工作量约为 **220 个不同编码**，而不是 366 行。数据中没有姓名、NRIC、电话、地址等直接标识符。

## 3. 数据质量问题（已核实，每一条都必须有处理规则）

| ID | 问题 | 证据 |
|---|---|---|
| DQ1 | case visit 中 `Case-4-03` 出现两次，40 列完全相同 | 22 行，21 个不同 Case_No |
| DQ2 | **lab 的 Case_No 与 case visit 完全对不上**。每名患者只有 1 个 lab Case_No；162 行中只有 2 行落在同一患者的住院时段内；有 2 名患者的检验日期附近没有任何住院记录 | `profiling/deep.py` 的输出（只保存在本地，不提交，因为含原始 ID） |
| DQ3 | 20 条用药医嘱早于本次入院 0.6–6.1 小时 | 例如 AMI 入院前 0.6 小时开出的 Aspirin 和 Prasugrel |
| DQ4 | surgical 的 operation_date 与 Adm_DateTime 7/7 完全相同 | 推测手术时间只是复制了入院时间 |
| DQ5 | Excel 损坏：2 行 Insulin 的 Dosage_Ordered 变成了 `2022-07-03`；1 行 Norepinephrine 的剂量是 `0 - 2` mcg/kg/min | — |
| DQ6 | 出生和死亡只有年份。两名死亡患者的死亡年份都晚于各自最后一次事件 | — |
| DQ7 | 诊断码是 ICD-10 格式，不带小数点，有 5–6 位码和 U/Y 码，推测为 **ICD-10-AM**。列名 `No_of_Secondary_Diagnosis_ICD9` 有误导性：次诊断条数只与 `..._Subvention` 列 22/22 一致 | — |
| DQ8 | 同一次住院的次诊断中 `Y9222` 出现两次（2 次 visit）。这符合 ICD-10-AM 中“外因码后接场所码”的规则，不属于错误 | 新核实 |
| DQ9 | 4 行 Sodium 的 Test_Code 为空；结果中有 `<2.0`、`Non-Reactive`、`B`、`Positive` 和一条约 66 字符的长句 | 长句会超出 `value_source_value varchar(50)` |
| DQ10 | Religion 和 Marital_Status 的取值中有 `"No Mapping"`，含义是未知 | — |
| DQ11 | xlsx 文件元数据：created 2022-11-03，modified 2022-11-07 | 可作为 `CDM_SOURCE.source_release_date` 的依据 |

分布：住院主要集中在 1 名患者身上（Patient-4 有 14 次，其余 4 人共 7 次）。住院类型组合只有 3 种：Emergency + A&E（17 次）、Emergency + SOC（2 次）、Day Surgery + SOC（2 次）。

## 4. 官方依据（已抓取，存放在 `sources/`）

- OMOP CDM v5.4 中 10 张表的字段定义：Required 标记和 ETL Conventions，见 `sources/cdm54_extract.md`
- Book of OHDSI 第 6 章（Usagi、Maps to、允许映射到 concept 0）和第 5 章（Vocabularies）的摘录
- **Athena 拒绝脚本访问（HTTP 403）。本次没有核实任何 Concept ID。** 所有 ID 都必须在 Athena 网页上人工查证，或者下载 vocabulary 后在本地查表。

## 5. 仍然未知的信息

| ID | 未知项 | 影响 |
|---|---|---|
| K1 | 课程评分标准和提交格式 | 决定交付范围 |
| K2 | Athena 是否收录 ICD-10-AM，以及 TOSP | 决定诊断和手术怎么映射 |
| K3 | lab Case_No 代表什么 | 决定 lab 是否挂到某次 visit |
| K4 | operation_date 是否是真实的手术时间 | 决定 procedure_datetime 是否填写 |
| K5 | Insulin 的真实剂量 | 无法恢复，只记录在案 |
| K6 | 检验单位 | 只能设为 NULL |
| K7 | 诊断的 provenance：Mediclaim 和 Subvention 属于理赔还是 EHR | 决定 condition_type_concept_id |
