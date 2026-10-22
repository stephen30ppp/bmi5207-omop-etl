# 08 · 六人分工与交付接口

**原则**
- 分工按**不同编码数**平衡工作量，而不是按行数。
- 每份 mapping 都由另一名成员交叉审核。
- 最终的 CSV 只能由统一的 pipeline 生成，任何人都不得手工编辑。

## 1. 分工

| 成员 | ETL 职责 | Mapping（主做 → 审核人） | 其他职责 | 交付接口 |
|---|---|---|---|---|
| **P1 技术负责人** | `load`、`clean`、`deid`、`ids`、`router`、`write`、`run`；OBSERVATION_PERIOD、CDM_SOURCE；持有 secret；搭 CI | 手术和人口学的审核人 | Day 1 下载 Athena vocabulary；冻结接口契约；每天跑一次全量集成；向课程方确认 U1、U3 | stage2 parquet/CSV、`ETL_CONVENTIONS.md`、`cdm54_columns.yaml`、`manifest.json` |
| **P2 人口学 + 手术** | PERSON、DEATH、OBSERVATION（demo）、PROCEDURE_OCCURRENCE（手术源） | 人口学 7 个值、手术 6 个码 → P1 | **APGAR 一页报告负责人**（见 §3） | `build_person.py`、`build_procedure.py`、mapping CSV |
| **P3 就诊** | VISIT_OCCURRENCE（去重）、visit/discharge/type 规则表 | 诊断中 U/W/X/Y/Z 码 17 个 → P4；visit 规则 → P1 | 时间关系校验（T-DATE 系列） | `build_visit.py`、`visit_rules.csv` |
| **P4 诊断** | CONDITION_OCCURRENCE 的拆分和按 domain 路由 | 诊断中 A–T 码约 55 个 → P3 | 在 Day 2 前确认 ICD-10-AM 是否在 Athena 中（U2） | `build_condition.py`、`diagnosis_map.csv` |
| **P5 检验** | MEASUREMENT，包括 `parse_result`、定性结果、operator | Lab 64 个、定性值 7 个 → P6 | 完成 GHB/GHB2 等的临床审核 | `build_measurement.py`、`lab_map.csv` |
| **P6 药品** | DRUG_EXPOSURE，包括 `parse_dose`、组分拆分、sig | 药品 73 个 → P5 | 药品与诊断的合理性检查，例如 Warfarin 与 I48/INR | `build_drug.py`、`drug_map.csv` |

人工工作量大致为：P4 约 55 个码，P3 约 17 个码加规则，P5 约 71 个，P6 约 73 个，P2 约 13 个加 APGAR，P1 负责集成。

**与原小组规划的差异**
- 原计划由 1 人负责 case_visit，现在拆成 P3（visit）和 P4（诊断），因为 72 个诊断码是最大的映射负担。
- 原计划 lab 和药品各 2 人，现在改为 1 人主做、另 1 人交叉审核，审核同样计入工作量。

## 2. 统一接口（Day 1 冻结）

```python
# 每个 build_* 都是纯函数，只读 stage2 和 APPROVED 的 mapping
def build(staged: dict[str, pd.DataFrame], vocab: VocabIndex, ctx: RunContext) -> list[EventRecord]

@dataclass
class EventRecord:
    default_table: str          # 映射失败时写入的表
    person_id: int
    visit_occurrence_id: int | None
    start: datetime             # 已偏移
    source_value: str
    source_concept_id: int      # 没有填 0
    map_rows: list[MapRow]      # 来自 vocab.lookup()，可能一对多
    fields: dict                # 各表特有字段，如 value_as_number、sig
    lineage: dict               # 源文件、行号、伪名 token
```

`router.py` 根据 `map_rows[i].target_domain_id` 把记录分发到对应的表，再由 `ids.py` 统一分配主键，由 `write.py` 统一写出。

## 3. APGAR 一页报告（独立 workstream，P2 负责，P5 审核）

1. **必须修正**：初稿第一段写的是可以 “determine within seconds whether resuscitation is required”。ACOG/AAP 指出，Apgar 评分不应用来决定是否开始复苏，复苏也不应等到 1 分钟评分之后才开始。改为：用于描述新生儿出生后的状态，以及记录对复苏的反应。
2. 按 Purpose、Development、Five Components、Data Structure Design 四部分压缩到一页。
3. 不纳入 ETL 的验收标准。

## 4. 协作规则

- Git：每人一个分支。PR 需要 P1 和一位同伴审核通过，CI（pytest）全部通过才能合并。
- 每个 PR 必须包含：source-to-target 变更说明、mapping 增量、行数对账结果、测试。
- 每天由 P1 跑一次 `python -m etl.run`，把对账表发到群里。
- 只有 P1 接触 stage1 和 secret。
