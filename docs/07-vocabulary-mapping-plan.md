# 07 · Athena 术语映射计划

**铁律**：任何 concept ID 都必须在 Athena 中实际查证，不得凭记忆填写。ETL 只读取 `status = APPROVED` 的行；mapper 和 reviewer 必须是**两个不同的人**。

## 1. 工作量（已核实）

| Domain | 不同编码数 | 源 vocabulary | 自动化程度 | 主映射人 / 审核人 |
|---|---|---|---|---|
| 诊断：A–T、非外因码 | 约 55 | ICD-10-AM？（U2） | 补小数点后在本地精确查 `Maps to`，大部分可以自动出候选 | P4 / P3 |
| 诊断：U/W/X/Y/Z 码 | 17 | 同上 | 同上；预计多数会路由到 Observation domain | P3 / P4 |
| Lab | 64 | 本地码 | Usagi 根据 Short_Text 生成候选 | P5 / P6 |
| 定性结果 + operator | 约 7 | 自由文本 | 人工 | P5 / P6 |
| 药品 | 73 | 本地码 | Usagi 根据 Cluster 描述生成候选 | P6 / P5 |
| 手术 | 6 | TOSP？（U5） | 人工按描述映射到 SNOMED | P2 / P1 |
| 人口学 | 7 个值 | 自由文本 | 人工 | P2 / P1 |
| Visit 规则、discharge、type concept | 约 12 | 固定值 | 人工 | P3、P1 / P1 |
| **合计** | **约 240** | | | |

## 2. 流程

1. **Day 1，P1：下载 Athena vocabulary bundle。** 浏览器登录 athena.ohdsi.org，选择 SNOMED、LOINC、RxNorm、RxNorm Extension、ICD10、ICD10CM、ICD10AM（如果有）、Gender、Race、Visit、Type Concept、Condition Status、Meas Value Operator、UCUM、CDM。记下版本号。
   - 下载失败时改为在网页上逐个检索，mapping sheet 的 schema 不变。
2. **Day 1，自动抽码**：`src/extract_codes.py` 按 domain 输出 `mappings/<domain>_todo.csv`，列出不同编码、描述、频次和上下文。
3. **Day 2，自动生成候选**：
   - ICD：补小数点（`I2511` 变成 `I25.11`），按 ICD10AM → ICD10 → ICD10CM 的顺序精确匹配，再沿 `Maps to` 和 `Maps to value` 取标准 concept。
   - 精确匹配失败的才截断，作为候选，标 equivalence = WIDER、status = PROPOSED，**不能自动批准**（04 D4）。
   - Lab、药品、手术：导入 Usagi 生成候选，过滤条件为 Standard + 对应 domain。
4. **Day 2–4，人工审核**：按频次从高到低处理。审核时检查 4 项：`standard_concept = 'S'`、`invalid_reason IS NULL`、有效期包含当天、domain 与目标表一致。
5. **Day 4，冻结**：把 mapping 快照提交到 git，记录 vocabulary_version。之后如需修改，必须重新审核。

## 3. Mapping sheet schema（全组统一，每个 domain 一个 CSV）

```
mapping_group_id, source_table, source_field, source_code, source_description,
source_vocab_hint, frequency, context, map_seq, relationship,
target_concept_id, target_concept_name, target_vocabulary_id, target_domain_id,
target_concept_class_id, standard_concept, valid_start_date, valid_end_date, invalid_reason,
value_as_concept_id, equivalence, status, mapping_method,
mapper, reviewer, review_date, vocab_version, rationale, issue_id
```

| 列 | 取值 |
|---|---|
| relationship | `Maps to` / `Maps to value` / `manual` |
| equivalence | `EQUAL` / `WIDER` / `NARROWER` / `INEXACT` / `UNMATCHED` |
| status | `DRAFT` → `PROPOSED` → `APPROVED`；或 `REJECTED` / `UNMAPPABLE` / `NEEDS_CLINICAL_REVIEW` |
| mapping_method | `vocab_sql` / `athena_web` / `usagi` / `manual` |

## 4. 各 domain 的规则

- **诊断**：按 target_domain_id 路由到相应的表。`Maps to value` 的结果写入 value_as_concept_id。外因码和对应的场所码（例如 Y442 + Y9222）各自映射，不合并。
- **Lab**：选择**不依赖单位**的 LOINC。两种 HbA1c（GHB 和 GHB2）、Creatinine 这类性质有歧义的标 `NEEDS_CLINICAL_REVIEW`，推断理由写进 rationale（04 D14）。
- **药品**：选源数据能支撑的最细粒度。
  - 描述中有强度和剂型（如 "Fentanyl 100mcg/2mL Inj"）→ Clinical Drug
  - 只有成分和剂型 → Clinical Drug Form
  - 只有成分 → Ingredient
  - **不得用 Dosage_Ordered 反推强度。**
  - 复方药映射到单个复方 concept。
  - 营养品、护肤品、FFP 如果没有 Drug domain 的标准 concept，按实际 domain 路由；仍然找不到的填 0。
- **手术**：映射到 SNOMED Procedure。复合手术（例如冠脉造影加血管成形）可以一对多，用 map_seq 编号。
- **人口学**：Male、Female、Chinese、Buddhism、Married 各查一次。"No Mapping" 不映射。

## 5. 映射失败和一对多的处理

| 情况 | 处理 |
|---|---|
| 找不到合适的标准 concept | status = UNMAPPABLE，concept 填 0，记录写入默认表并列入 `unmapped.csv`，附频次 |
| 一个源码有多个 `Maps to` | 每个目标生成一行，共享 mapping_group_id 和同一条源 lineage；对账时按展开后的数量计算 |
| `Maps to value` | 合并为一条记录：主 concept 加上 value_as_concept_id |
| 同成分的不同药品 | 复用已有结果（例如两种 Omeprazole、口服和注射用 Metoclopramide） |

**覆盖率报告**（写入报告的 Results 部分）：按 domain 统计“映射成功的编码数 / 不同编码总数”和“映射成功的行数 / 总行数”，并列出全部 UNMAPPABLE 编码。
