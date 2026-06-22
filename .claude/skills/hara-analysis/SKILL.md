---
name: hara-analysis
description: 面向 Claude Code 的汽车 ISO 26262 HARA 分析 skill。用于从功能需求文档（尤其是 .docx）提取 item/function，分阶段生成 malfunction、整车级危害、危险事件、S/E/C、ASIL、安全目标，并导出 requirements.md 约定的四个 sheet Excel。触发场景包括：HARA 分析、危害分析与风险评估、ASIL 分配、安全目标生成、EPB/灯光/制动/转向/动力/车身控制等汽车功能安全分析、需要替代人工初稿并让工程师评审的 HARA 表格。
---

# HARA Analysis

你是汽车功能安全 HARA 分析负责人。目标不是把表格填满，而是产出可被工程师评审、可追溯、少漏项、少伪场景的 HARA Excel。

## 核心原则

1. 分阶段生成，不要一次性写完整表。按 `item -> function -> malfunction -> vehicle hazard -> scenario -> review -> S/E/C -> SEC grounding review -> safety goal -> deterministic review -> review repair -> export` 推进。
2. 严格控制上下文。优先使用 `scripts/claude_hara_pipeline.py`，让每个阶段在独立 Claude 进程中运行，只通过 JSON artifact 传递必要上游数据；不要在同一会话里连续完成所有阶段。
3. 机械判断交给脚本。ASIL、枚举、ID、sheet 追溯、重复场景和 Excel 导出必须用 `scripts/hara_tool.py` 校验。
4. 危险事件必须由故障触发。若移除故障后同一危险事件仍会发生，该场景无效。
5. S/E/C 必须由模型基于场景事实自主推导，不得为了得到某个 ASIL 反推等级，也不得由脚本用功能族模板改写解释。
6. QM 条目的安全目标、安全状态、FTTI 必须为空；非 QM 条目继承所属故障 MF 的车辆级安全目标、安全状态和 FTTI。
7. `sg_sum` 必须按每个故障 MF 的最高 ASIL 代表条目逐条生成；如果该故障 MF 的最高 ASIL 为 `QM`，则该故障不生成 SG。不要因为不同 MF 的安全目标文字相似而跨 MF 合并。
8. 所有输出使用中文；保留英文标准字段名，例如 `Severity 'S'`、`ASIL Level`。
9. 工具可以发现问题、应用模型返回的修订和重算 ASIL，但不得由脚本按系统名或故障名生成 S/E/C 解释。

## 必读和按需读取

先读：

- `references/workflow.md`：端到端流程、上下文切片和质量门。
- `references/context-isolation.md`：真正隔离上下文的阶段边界和 Claude 调用方式。
- `references/output-contract.md`：最终 JSON 结构、四个 Excel sheet 字段和编号规则。
- `references/sheet1-malfunction-guide.md`：sheet1 引导词适用性、故障描述粒度和常见误判。

按阶段读取：

- `references/hara-core.md`：HARA、item、malfunction、hazard、hazardous event、安全目标的定义和边界。
- `references/function-patterns.md`：功能族知识。只读取与当前系统相关的段落；不要整篇复述进输出。
- `references/sec-guide.md`：只在 S/E/C 评级阶段读取；场景生成阶段禁止读取。
- `references/sec-grounding-audit.md`：只在 SEC 场景扎根复核阶段读取；用于检查 SEC 是否引入了场景中没有的事实。
- `references/review-rules.md`：场景评审、SEC 评审、最终评审时读取。

枚举和工具：

- `assets/operation_scenarios.json`：HARA sheet 场景字段允许值。
- `assets/vehicle_hazards.json`：sheet2 整车级危害允许值。
- `scripts/hara_tool.py`：抽取 docx、校验 JSON、导出 Excel、生成评审报告。
- `scripts/claude_hara_pipeline.py`：用多个独立 Claude 调用执行端到端 HARA 流水线。

## 标准工作流

### 0. 建立工作目录

为每个输入文档创建独立目录，例如：

```bash
python .claude/skills/hara-analysis/scripts/hara_tool.py init --source light.docx --out work/light_hara
python .claude/skills/hara-analysis/scripts/hara_tool.py extract-docx --source light.docx --out work/light_hara/source
```

如果要让 Claude 自动执行，使用隔离流水线：

```bash
python .claude/skills/hara-analysis/scripts/claude_hara_pipeline.py run --source light.docx --out work/light_hara --system LIGHT --min-scenarios 4
```

调试上下文时先生成 prompt，不调用 Claude：

```bash
python .claude/skills/hara-analysis/scripts/claude_hara_pipeline.py run --source light.docx --out work/light_hara --system LIGHT --dry-run-prompts
```

多功能需求文档必须逐功能分析。每个 Claude 子调用只读取当前功能或当前故障所需片段。SEC 首次评级只读取已评审通过的场景和 `sec-guide.md`；SEC 复核只读取同一条场景、SEC 草案、`sec-guide.md` 和 `sec-grounding-audit.md`。

### 1. Item 和功能提取

读取源文档目录、功能清单、功能小节，形成 item 定义：

- 系统名、功能名、功能边界、输入/输出、工作电源、操作模式、关键前置条件。
- 若文档缺少车辆类型、市场、ODD、HMI、执行器架构，写入 `assumptions`，不要虚构为事实。
- `derive_mf.子功能` 必须优先来自功能清单表中的功能名称。功能内部逻辑、提示、诊断、状态上报只有在功能清单明确列为独立功能时才可单独成行；否则作为该功能的故障来源或场景依据。
- 多个功能时，按功能逐一产出 `derive_mf` 行，功能之间只共享 item 级事实。

### 2. Malfunction 派生

使用 `output-contract.md` 的 8 个引导词列：

`功能丧失`、`过大`、`过早`、`过小`、`过晚`、`非预期激活`、`卡滞`、`方向错误`。

每个非空引导词写成 `MF101 具体故障描述` 形式。编号是 `MF + 功能序号 + 当前功能中非空引导词序号`，不是引导词固定序号。一个引导词可包含多个同 ID 故障，但进入 sheet2 时要拆成多条。

故障描述必须是“功能行为偏离”，不是根因。例如写“近光灯在夜间行驶中无法点亮”，不要写“驱动电路断路”。

生成 sheet1 时必须读取 `references/sheet1-malfunction-guide.md`，先建立当前功能的行为模型，再逐引导词判断故障是否逻辑存在。只要功能故障存在，就写入 sheet1；不要因为后续可能是 QM、暂时想不到场景、或源文档没有明示该故障就删掉。安全相关性在 sheet2/HARA 判断。

行为模型至少包含：触发源、允许条件、执行动作、目标状态、物理作用量、响应时序、相反方向/状态、反馈提示。每个引导词都要基于这些维度判断是否适用，而不是套用样例答案。

### 3. 整车级危害映射

读取 `assets/vehicle_hazards.json`，只能选择允许值。每个 sheet2 条目：

- 复用 sheet1 的故障描述。
- 选择一个最贴切的整车级危害。
- 若确实没有人身安全危害，选择 `无危害` 并在备注说明。

### 4. 场景和危险事件生成

每个安全相关故障/危害至少生成 4 条候选场景，复杂或高风险故障生成 6-8 条候选场景；评审去重后通常保留不少于 3 条有效 HARA 场景。仅当 `整车级危害=无危害` 或功能操作域极窄且有明确理由时，才可少于 3 条。

候选场景必须覆盖这些原型：

- 最高合理严重度路径。
- 高频暴露路径。
- 低可控性路径。
- 功能边界/操作域边界路径。
- 低风险对照路径，通常用于说明 QM 或无危害。

生成场景时先写内部检查：

```text
故障 -> 异常车辆行为 -> 必要物理/操作条件 -> 风险对象及位置 -> 伤害机制 -> 危险事件
```

然后执行反事实检查：移除故障后，同一危险事件是否仍成立。若成立，改写或删除场景。

HARA sheet 的道路、环境、车辆状态、车速、特殊要素必须来自 `assets/operation_scenarios.json`。不要用 `ALL` 逃避具体分析，除非该条件真的不影响风险机制，并在 `附加条件` 解释。

### 5. S/E/C、ASIL 和安全目标

进入评级阶段后再读 `references/sec-guide.md`。

- `E-解释` 必须说明暴露场景频率或使用占比。
- `可能的后果('S'的理由)` 必须说明受伤对象、碰撞/伤害机制、速度或能量依据。
- `C-解释` 必须说明感知性、反应时间、可用操作、空间约束、驾驶员是否在车上。
- `结果ASIL` 用脚本计算后校验，不能手算自由改写。
- 非 QM 的安全目标必须车辆级表达，避免写成传感器、报文、算法、诊断机制等实现方案。
- 安全目标生成以故障 MF 为粒度：先找该 MF 所有 HARA 场景中的最高 ASIL 条目，再用该代表条目的危险事件生成 SG；该 MF 最高 ASIL 为 QM 时不生成 SG。
- 同一 MF 的非 QM HARA 行使用该 MF 最高 ASIL 代表条目的安全目标、安全状态和 FTTI；不同 MF 即使目标文字接近，也在 `sg_sum` 中分别保留。

SEC 评级和复核阶段可以读取与当前系统相关的一小段 `function-patterns.md` 作为功能物理知识，但不得把它当作固定答案。SEC 评级后必须执行 `sec_grounding_review`。复核阶段不是功能族规则库，不得按 `light`、`EPB` 等系统名套答案；它只做通用场景扎根审计：

- SEC 解释中的每个场景前提必须能在本行字段或附加条件找到依据。
- E 必须解释当前场景暴露频率，不能把故障概率或模板化场景当作 E。
- C 必须与场景中“未及时发现、驾驶员离车、距离较近、车速高、弯道、坡道、空间不足”等事实一致。
- 若 SEC 草案与场景不一致，由复核模型基于本行事实重做 S/E/C；脚本不得生成领域化 E/C/S 理由。

### 6. 生成 JSON、校验、导出 Excel

先写最终分析 JSON，例如 `work/light_hara/analysis.json`。结构见 `references/output-contract.md`。

运行：

```bash
python .claude/skills/hara-analysis/scripts/hara_tool.py validate --analysis work/light_hara/analysis.json --strict
python .claude/skills/hara-analysis/scripts/hara_tool.py export --analysis work/light_hara/analysis.json --out work/light_hara/hara.xlsx --review-out work/light_hara/review.md
```

如果校验失败，修复 JSON 后重跑。不要交付未通过校验的 Excel。

### 7. 最终评审

读取 `references/review-rules.md`，结合脚本生成的 `review.md` 做最终人工标准自评：

- 是否漏掉文档中明确功能。
- 是否每个故障都能追溯到正常功能。
- 是否每个危险事件都有故障必要性。
- 是否场景物理一致、操作域一致、风险对象在危险路径内。
- 是否 S/E/C 理由均来自场景事实。
- 是否 ASIL 与矩阵一致。
- 是否每个最高 ASIL 非 QM 的故障 MF 都有一条 SG，最高 ASIL 为 QM 的故障 MF 没有 SG。
- 是否同一 MF 的非 QM 条目继承最高 ASIL 代表条目的车辆级安全目标和安全状态。

若存在 blocking 问题，修复后重新导出。

若工具评审发现 HARA 行问题，优先使用 pipeline 的 `review_repair` 阶段：只把 finding 和对应 HARA 行交给 Claude 复核修订。脚本不得把 finding 固化成特定系统的规则；修订仍必须来自当前行场景事实、功能物理机制和通用评审规则。

## 交付物

最终至少交付：

- HARA Excel：四个 sheet，名称固定为 `derive_mf`、`mf_vehicle_hazards`、`HARA`、`sg_sum`。
- 校验/评审报告：说明通过项、警告项、需工程师关注的假设。
- 若源文档信息不足，列出需要工程师确认的最小问题清单。
