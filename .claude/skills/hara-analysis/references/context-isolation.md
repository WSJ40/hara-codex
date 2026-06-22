# 上下文隔离执行规范

## 为什么需要独立进程

Claude 的同一会话会累积上下文。即使每个阶段“分批读文件”，SEC 阶段仍可能受到前面 malfunction 选择、候选场景草稿、被拒绝场景和安全目标预期的污染。因此 HARA 分析必须用独立 Claude 调用模拟不同评审角色，只通过结构化 JSON artifact 传递必要信息。

## 推荐命令

```bash
python .claude/skills/hara-analysis/scripts/claude_hara_pipeline.py run --source light.docx --out work/light_hara --system LIGHT --min-scenarios 4
```

调试模式：

```bash
python .claude/skills/hara-analysis/scripts/claude_hara_pipeline.py run --source light.docx --out work/light_hara --system LIGHT --dry-run-prompts
```

## 阶段输入边界

### item_functions

允许输入：

- `source/source.md`
- `source/source_index.json`
- `source/function_catalog.json`
- `references/hara-core.md`
- `references/output-contract.md` 中 item 和 sheet1 相关片段

禁止输入：

- SEC 指南
- 安全目标模板
- 之前项目的 HARA 表

### derive_mf

每个功能独立调用。

允许输入：

- item 摘要
- 当前功能源文档片段
- 引导词定义
- sheet1 引导词适用性指南
- 当前功能族模式

禁止输入：

- 其他功能的完整故障列表
- 场景 SEC 评级规则
- 期望 ASIL

### map_hazard

允许输入：

- 当前功能 malfunction
- 整车级危害枚举
- vehicle hazard 定义

禁止输入：

- 场景生成草稿
- SEC 指南

### scenario_generate

每个故障/危害独立调用。

允许输入：

- item 摘要
- 当前功能片段
- 当前故障和整车危害
- operation scenario 枚举
- 场景生成规则和反模式

禁止输入：

- SEC 指南
- ASIL 矩阵
- 安全目标要求

输出要求：

- 先生成 4-8 条候选场景。
- 每条包含风险机制标签：最高严重度、高暴露、低可控性、边界工况、常见工况、低风险对照。
- 每条包含反事实检查结论。

### scenario_review

允许输入：

- 一个故障/危害的候选场景
- review rules
- operation scenario 枚举

禁止输入：

- 生成器自由推理
- SEC 指南
- 安全目标要求

### sec_rate

每条通过评审的场景独立调用。

允许输入：

- 一条 accepted scenario
- `sec-guide.md`

禁止输入：

- 被拒绝候选场景
- malfunction 生成过程
- 安全目标草稿

### sec_grounding_review

每条已评级场景独立调用。

允许输入：

- 同一条 accepted scenario
- 当前 SEC 草案
- `sec-guide.md`
- `sec-grounding-audit.md`

禁止输入：

- 用户评审标注或期望答案
- 其他场景的 SEC 结果
- 系统专项后处理规则
- 早期故障生成和场景生成自由推理

输出要求：

- 审计 SEC 解释是否完全扎根于当前场景字段和附加条件。
- 如果通过，返回原 SEC。
- 如果不通过，只基于本行事实重做 SEC。
- 不得用“评级校正”“修正”等后处理措辞。

### safety_goal

允许输入：

- 非 QM rated scenarios
- HARA 核心定义中 safety goal 部分
- output contract 中 `sg_sum` 部分

禁止输入：

- 组件设计方案
- 诊断实现方案

### review_repair

允许输入：

- 工具评审 finding
- finding 对应的 HARA 行
- `sec-guide.md`
- `sec-grounding-audit.md`
- `review-rules.md`
- 当前系统相关的功能族物理知识

禁止输入：

- 用户期望答案或历史人工标注
- 不相关 HARA 行的完整上下文
- 脚本中的专项修正规则

输出要求：

- 只修订 finding 指向的行。
- 修订来自当前行场景事实和功能物理机制。
- 不得按系统名或故障名套固定评级。

## artifact 命名

建议输出：

```text
work/<case>/
  source/
  stages/
    00_item_functions.prompt.md
    00_item_functions.json
    10_derive_mf_<function>.prompt.md
    10_derive_mf_<function>.json
    20_hazard_<function>.json
    30_scenario_<fault>.json
    40_scenario_review_<fault>.json
    50_sec_<scenario>.json
    55_sec_grounding_<scenario>.json
    60_safety_goal.json
    70_review_repair.json
    71_safety_goal_after_repair.json
  analysis.json
  hara.xlsx
  review.md
```
