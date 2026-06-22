#!/usr/bin/env python3
"""Run HARA analysis with isolated Claude Code stage contexts.

The important property is context isolation: every generation/review/rating
stage is a fresh `claude -p --no-session-persistence` call. Stages exchange only
JSON artifacts on disk.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REF_DIR = SKILL_DIR / "references"
ASSET_DIR = SKILL_DIR / "assets"
HARA_TOOL = SCRIPT_DIR / "hara_tool.py"
ASIL_ORDER = {"QM": 0, "A": 1, "B": 2, "C": 3, "D": 4}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


def shell(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=str(cwd), check=True)


def find_claude(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env_bin = os.environ.get("HARA_CLAUDE_BIN")
    if env_bin:
        return env_bin
    win_bin = Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
    if win_bin.exists():
        return str(win_bin)
    return "claude"


def claude_prompt_ref(path: Path, cwd: Path) -> str:
    try:
        rel = path.resolve().relative_to(cwd.resolve())
        ref = rel.as_posix()
    except ValueError:
        ref = path.resolve().as_posix()
    return "@" + ref


def run_claude(prompt_path: Path, claude_bin: str, cwd: Path, max_budget: str | None) -> Any:
    prompt = read_text(prompt_path)
    for attempt in range(2):
        task_path = prompt_path
        if attempt == 1:
            raw_path = prompt_path.with_suffix(prompt_path.suffix + ".raw0.txt")
            raw = read_text(raw_path) if raw_path.exists() else ""
            task = (
                "下面是一个 Claude 子任务的输出，但不是合法 JSON。请只修复 JSON 语法，不要改变字段语义，"
                "只输出合法 JSON，不要输出 Markdown。\n\n"
                "原始任务要求：\n"
                + prompt[-6000:]
                + "\n\n待修复输出：\n"
                + raw
            )
            task_path = prompt_path.with_suffix(prompt_path.suffix + ".repair.md")
            write_text(task_path, task)
        cmd = [
            claude_bin,
            "-p",
            "执行此文件中的任务，只输出该任务要求的合法 JSON，不要总结文件内容，不要询问是否执行："
            + " "
            + claude_prompt_ref(task_path, cwd),
            "--no-session-persistence",
            "--permission-mode",
            "acceptEdits",
            "--tools",
            "",
            "--output-format",
            "text",
        ]
        if max_budget:
            cmd.extend(["--max-budget-usd", max_budget])
        result = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, encoding="utf-8", errors="replace")
        prompt_path.with_suffix(prompt_path.suffix + f".raw{attempt}.txt").write_text(
            result.stdout or "", encoding="utf-8", newline="\n"
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Claude stage failed: {prompt_path}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        try:
            return extract_json(result.stdout)
        except json.JSONDecodeError:
            if attempt == 1:
                raise
    raise RuntimeError(f"unreachable Claude JSON retry path: {prompt_path}")


def get_stage_json(path: Path, prompt_path: Path, claude_bin: str, cwd: Path, max_budget: str | None, resume: bool) -> Any:
    if resume and path.exists():
        return read_json(path)
    value = run_claude(prompt_path, claude_bin, cwd, max_budget)
    write_json(path, value)
    return value


def source_excerpt(source_md: str, function_name: str, max_lines: int = 140) -> str:
    lines = source_md.splitlines()
    first = next((i for i, line in enumerate(lines) if function_name in line), 0)
    start = max(first - 8, 0)
    end = min(first + max_lines, len(lines))
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines[start:end], start))


def prompt_header(stage: str) -> str:
    return (
        f"# Stage: {stage}\n\n"
        "你是汽车功能安全 HARA 分析专家。只输出合法 JSON，不要输出 Markdown、解释或代码块。\n"
        "当前阶段是独立上下文；只能使用本 prompt 中给出的输入，不要引用其他阶段的隐藏推理。\n\n"
    )


def markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_match = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(text)
    return text[match.start() : end].strip()


def relevant_function_pattern(project: dict[str, Any], hazard_row: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(project.get("system_name", "")),
            " ".join(str(v) for v in project.get("source_functions", []) if v),
            str(hazard_row.get("故障描述", "")),
            str(hazard_row.get("整车级危害", "")),
            str(hazard_row.get("整车危害", "")),
        ]
    ).lower()
    candidates = [
        ("外部照明/前照灯", ["light", "lamp", "近光", "远光", "照明", "前照灯", "灯光"]),
        ("电子驻车制动 EPB/驻车保持", ["epb", "驻车", "电子驻车", "拉起", "释放"]),
        ("制动系统", ["brake", "制动", "刹车", "减速"]),
        ("转向系统", ["steer", "转向", "横向", "方向盘"]),
        ("动力/驱动系统", ["drive", "动力", "驱动", "加速", "扭矩"]),
        ("HMI/提示/报警", ["hmi", "提示", "报警", "告警", "信息"]),
    ]
    patterns = read_text(REF_DIR / "function-patterns.md")
    for heading, keywords in candidates:
        if any(keyword.lower() in text for keyword in keywords):
            section = markdown_section(patterns, heading)
            if section:
                return section
    return ""


def build_item_prompt(source_md: str, function_catalog: dict[str, Any], system: str) -> str:
    return (
        prompt_header("item_functions")
        + read_text(REF_DIR / "hara-core.md")
        + "\n\n"
        + read_text(REF_DIR / "output-contract.md")
        + "\n\n## 源功能清单\n"
        + json.dumps(function_catalog, ensure_ascii=False, indent=2)
        + "\n\n## 源文档\n"
        + source_md
        + "\n\n输出 JSON schema：\n"
        + json.dumps(
            {
                "project": {
                    "system_name": system,
                    "source_file": "string",
                    "item_definition": "string",
                    "source_functions": ["源文档功能清单中的功能名"],
                    "assumptions": ["string"],
                },
                "function_slices": [
                    {
                        "name": "必须来自 source_functions",
                        "normal_behavior": "string",
                        "operating_domain": "string",
                        "source_evidence": ["string"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_derive_prompt(item: dict[str, Any], function_name: str, excerpt: str) -> str:
    return (
        prompt_header(f"derive_mf:{function_name}")
        + read_text(REF_DIR / "hara-core.md")
        + "\n\n"
        + read_text(REF_DIR / "sheet1-malfunction-guide.md")
        + "\n\n"
        + read_text(REF_DIR / "function-patterns.md")
        + "\n\n## item 摘要\n"
        + json.dumps(item, ensure_ascii=False, indent=2)
        + "\n\n## 当前功能源文档片段\n"
        + excerpt
        + "\n\n输出 JSON schema：\n"
        + json.dumps(
            {
                "function_behavior_model": {
                    "fault_object": "统一用于 sheet1 故障短语的功能对象名，如近光灯/EPB/驻车制动",
                    "trigger_sources": ["驾驶员请求/自动条件/系统状态变化"],
                    "allowed_conditions": ["电源/车速/状态/互锁条件"],
                    "actions": ["功能执行动作"],
                    "target_states": ["目标状态"],
                    "physical_effects": ["亮度/夹紧力/制动力/扭矩/角度/速度/持续时间等，没有则为空"],
                    "timing_relations": ["响应时间/保持时间/自动触发时机，没有则为空"],
                    "opposite_directions_or_states": ["打开-关闭/拉起-释放/左-右等，没有则为空"],
                    "feedbacks": ["显示/报警/提示，没有则为空"]
                },
                "derive_mf_row": {col: "" for col in [
                    "No.",
                    "子功能",
                    "功能丧失",
                    "过大",
                    "过早",
                    "过小",
                    "过晚",
                    "非预期激活",
                    "卡滞",
                    "方向错误",
                ]},
                "guideword_decisions": [
                    {
                        "guideword": "功能丧失/过大/过早/过小/过晚/非预期激活/卡滞/方向错误",
                        "exists": "yes/no",
                        "basis_in_behavior_model": "引用 function_behavior_model 中的触发源/动作/状态/作用量/时序/方向维度说明为什么存在或不存在",
                        "candidate_faults": ["存在时给出一个或多个功能级故障；不存在时为空数组"]
                    }
                ],
                "split_faults": [
                    {"fault": "MF101 ...", "guideword": "功能丧失", "safety_relevance": "yes/no + reason"}
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\n要求：子功能必须等于当前功能名；不要把内部逻辑拆成独立功能行。"
        + "\n先建立 function_behavior_model，再逐个判断 8 个引导词对应的功能偏离是否逻辑存在，最后输出 sheet1。"
        + "\n只要功能故障存在就写入 sheet1；不要因为安全相关性低、暂时想不到危害场景、或源文档没有明示该故障就删除。"
        + "\n故障描述必须是功能行为偏离，不能写场景、根因、危害后果或安全机制。"
        + "\n功能丧失保持概括，同一偏离不要按电源档、状态、休眠唤醒等前置条件重复拆分。"
        + "\n过大/过小/过早/过晚/非预期激活/卡滞/方向错误均必须从行为模型中的作用量、时序、状态和方向关系推导。"
        + "\n同一个异常行为在同一引导词内不要重复；不同引导词从不同角度提问时可以同时保留，例如“无法熄灭”属于功能丧失，“卡滞在点亮状态”属于卡滞。"
        + "\n功能丧失按 required control action 判断：当前功能负责的动作/目标状态没有提供即为功能丧失。双向状态控制功能必须分别考虑两个方向，例如近光灯无法点亮和近光灯无法熄灭。"
        + "\n过早只在当前功能自身拥有自动触发时机或阶段顺序时填写；上游自动判断逻辑不是当前功能时，不要把上游判断过早写成当前功能故障。"
        + "\n只分析当前子功能负责的行为偏离。对单向状态转换功能，起始状态卡滞导致无法达到当前功能目标，属于当前功能；目标状态卡滞导致无法执行相反功能，通常属于相反功能。例如拉起功能应保留“卡滞在释放状态无法拉起”，但通常不生成“卡滞在拉起状态无法释放”。"
        + "\n同一本质故障不要按操作域、允许条件或场景拆成多个 sheet1 故障；例如“未请求时拉起”和“行驶中拉起”若本质都是非预期拉起，sheet1 只写一个功能级非预期拉起。"
        + "\n非预期激活优先写状态改变本身，如“<功能对象>非预期拉起/点亮/释放/熄灭”；未请求、行驶中、超门限、休眠、电源档位等条件后续放到 sheet2/HARA。"
        + "\n所有故障描述统一采用“功能对象 + 偏离表现”的短语风格；同一功能行不要混用长条件句、场景句和短语句。"
        + "\n先确定 function_behavior_model.fault_object，所有 candidate_faults 和 split_faults 的故障正文都应以该对象开头或等价短对象开头；不要以“未请求/行驶中/驻车时/应/请求”等条件或句式开头。"
        + "\n如果当前功能的车辆级输出具有亮度、照度、夹紧力、制动力、扭矩、转角、速度、位置、温度等物理作用量，必须审查并通常填写过大和过小；不要因为源文档只写驱动开/关就忽略最终物理输出。"
        + "\n如果存在相反动作或状态，请区分：无请求或不满足条件发生动作为非预期激活；有请求A但执行相反B为方向错误。即使当前功能是单向转换，“请求当前动作却执行相反动作”也属于当前功能的方向错误。"
        + "\n同一引导词内不同动作/状态必须用分号拆分，禁止用“/”压缩，例如写“近光灯点亮响应过晚；近光灯熄灭响应过晚”，不要写“近光灯点亮/熄灭响应过晚”。"
        + "\n输出前按本清单自检并修正：作用量过大/过小是否漏填；双向功能丧失是否覆盖两个动作；方向错误是否漏填；非预期激活是否按条件重复；所有故障是否同一对象同一风格；过晚是否写成“响应过晚”而不是“延迟”。"
    )


def build_hazard_prompt(project: dict[str, Any], derive_rows: list[dict[str, Any]]) -> str:
    return (
        prompt_header("map_hazard")
        + read_text(REF_DIR / "hara-core.md")
        + "\n\n## 整车危害枚举\n"
        + read_text(ASSET_DIR / "vehicle_hazards.json")
        + "\n\n## project\n"
        + json.dumps(project, ensure_ascii=False, indent=2)
        + "\n\n## derive_mf\n"
        + json.dumps(derive_rows, ensure_ascii=False, indent=2)
        + "\n\n输出 JSON schema：\n"
        + json.dumps(
            {
                "mf_vehicle_hazards": [
                    {"No.": 1, "Milf_ID": "SYS_Milf_001", "故障描述": "MF101 ...", "整车级危害": "枚举值", "备注": "string"}
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_hazard_prompt_from_faults(project: dict[str, Any], split_faults: list[dict[str, Any]]) -> str:
    return (
        prompt_header("map_hazard")
        + read_text(REF_DIR / "hara-core.md")
        + "\n\n"
        + read_text(REF_DIR / "sheet2-hazard-guide.md")
        + "\n\n"
        + read_text(REF_DIR / "function-patterns.md")
        + "\n\n## 整车危害枚举\n"
        + read_text(ASSET_DIR / "vehicle_hazards.json")
        + "\n\n## project\n"
        + json.dumps(project, ensure_ascii=False, indent=2)
        + "\n\n## split_faults\n"
        + json.dumps(split_faults, ensure_ascii=False, indent=2)
        + "\n\n必须为 split_faults 中每一条故障生成 sheet2 条目，不能因为 safety_relevance 为 no/unknown 就省略。"
        + "如果暂未识别到明确整车级危害，整车级危害填写允许枚举 `无危害`，并在备注中说明判断依据。"
        + "同一 MF 编号下若有多个分号拆开的故障描述，必须逐条分开生成 sheet2 行，故障描述要与 sheet1 的单条故障完全一致。\n"
        + "输出 JSON schema：\n"
        + json.dumps(
            {
                "mf_vehicle_hazards": [
                    {"No.": 1, "Milf_ID": "SYS_Milf_001", "故障描述": "MF101 ...", "整车级危害": "枚举值", "备注": "string"}
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\n要求：整车级危害必须来自枚举；故障描述必须保留 MF 编号。"
        + "\n输出前自检：split_faults 有多少条，sheet2 至少应有多少条；每一条 split_faults.fault 都必须在 sheet2 的故障描述列精确出现。"
        + "\n不要把当前故障偷换成另一个引导词的故障，例如不要把作用量过大分析成非预期激活。"
    )


def build_scenario_prompt(
    project: dict[str, Any], hazard_row: dict[str, Any], function_excerpt: str, min_scenarios: int
) -> str:
    return (
        prompt_header(f"scenario_generate:{hazard_row.get('Milf_ID')}")
        + read_text(REF_DIR / "workflow.md")
        + "\n\n"
        + read_text(REF_DIR / "sheet2-hazard-guide.md")
        + "\n\n"
        + read_text(REF_DIR / "function-patterns.md")
        + "\n\n"
        + read_text(REF_DIR / "scenario-consistency-guide.md")
        + "\n\n"
        + read_text(REF_DIR / "review-rules.md")
        + "\n\n## operation scenarios 枚举\n"
        + read_text(ASSET_DIR / "operation_scenarios.json")
        + "\n\n## project\n"
        + json.dumps(project, ensure_ascii=False, indent=2)
        + "\n\n## 当前故障和整车危害\n"
        + json.dumps(hazard_row, ensure_ascii=False, indent=2)
        + "\n\n## 当前功能源文档片段\n"
        + function_excerpt
        + "\n\n禁止读取或使用 SEC/ASIL 指南。本阶段只生成候选场景和危险事件，不评级。\n"
        + f"输出至少 {max(min_scenarios + 1, 4)} 条候选场景，覆盖最高严重度、高暴露、低可控性、边界工况、常见工况、低风险对照等不同机制。\n"
        + "不要为了凑最高严重度而构造不符合驾驶习惯的场景；若故障是有请求时未达成（如无法点亮、请求点亮却熄灭），必须考虑驾驶员通常会立即发现并补救。\n"
        + "近光灯场景禁止偷换成远光灯故障；不能把近光灯持续点亮写成远光灯未关闭。\n"
        + "弱危害也要给出可评审的低风险/QM候选场景，不要只输出极端场景。\n"
        + "输出 JSON schema：\n"
        + json.dumps(
            {
                "candidates": [
                    {
                        "archetype": "最高严重度/高暴露/低可控性/边界工况/常见工况/低风险对照",
                        "fault_necessity": "移除故障后危险事件是否消失",
                        "道路类型": "枚举值",
                        "道路条件": "枚举值",
                        "环境条件": "枚举值",
                        "车辆状态": "枚举值",
                        "车速(km/h)": "枚举值",
                        "特殊要素": "枚举值",
                        "附加条件": "string",
                        "驾驶员是否在车上": "是/否/不涉及",
                        "危害事件": "string",
                        "有风险的人员": "string",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_scenario_review_prompt(hazard_row: dict[str, Any], candidates: dict[str, Any], min_scenarios: int) -> str:
    return (
        prompt_header(f"scenario_review:{hazard_row.get('Milf_ID')}")
        + read_text(REF_DIR / "review-rules.md")
        + "\n\n"
        + read_text(REF_DIR / "sheet2-hazard-guide.md")
        + "\n\n"
        + read_text(REF_DIR / "scenario-consistency-guide.md")
        + "\n\n"
        + read_text(REF_DIR / "function-patterns.md")
        + "\n\n## 当前故障和整车危害\n"
        + json.dumps(hazard_row, ensure_ascii=False, indent=2)
        + "\n\n## 候选场景\n"
        + json.dumps(candidates, ensure_ascii=False, indent=2)
        + f"\n\n保留不少于 {min_scenarios} 条有效且机制不同的场景；若少于该数量，必须给出 blocking finding。\n"
        + "评审时不要只保留高风险场景；低风险但因果有效的QM场景也应保留，用于证明风险边界。"
        + "剔除把近光灯当远光灯、把有请求失败当行驶中突然失效、或风险对象不在可照明路径内的场景。\n"
        + "输出 JSON schema：\n"
        + json.dumps(
            {
                "accepted": [
                    {
                        "道路类型": "枚举值",
                        "道路条件": "枚举值",
                        "环境条件": "枚举值",
                        "车辆状态": "枚举值",
                        "车速(km/h)": "枚举值",
                        "特殊要素": "枚举值",
                        "附加条件": "string",
                        "驾驶员是否在车上": "是/否/不涉及",
                        "危害事件": "string",
                        "有风险的人员": "string",
                        "review_rationale": "string",
                    }
                ],
                "findings": [{"status": "pass/fail/warning", "finding": "string", "required_action": "string"}],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_sec_prompt(project: dict[str, Any], hazard_row: dict[str, Any], scenario: dict[str, Any]) -> str:
    function_pattern = relevant_function_pattern(project, hazard_row)
    return (
        prompt_header("sec_rate")
        + read_text(REF_DIR / "sec-guide.md")
        + ("\n\n## 当前功能族物理知识\n" + function_pattern if function_pattern else "")
        + "\n\n## 只允许使用这一条场景事实\n"
        + json.dumps({"project": project, "hazard": hazard_row, "scenario": scenario}, ensure_ascii=False, indent=2)
        + "\n\n## SEC 输出约束\n"
        + "把 SEC 指南作为首次工程判断模型使用，直接基于本行场景事实给出 S/E/C。"
        + "不要写“评级校正”“修正”“按规则压低/提高”“根据指南调整”等后处理措辞；"
        + "不要复述规则原文，要解释本行为什么暴露频率、伤害严重度或可控性是该等级。\n"
        + "\n\n输出 JSON schema：\n"
        + json.dumps(
            {
                "E-解释": "string",
                "暴露频率'E'": "E0/E1/E2/E3/E4",
                "可能的后果('S'的理由)": "string",
                "Severity 'S'": "S0/S1/S2/S3",
                "C-解释": "string",
                "控制能力 'C'": "C0/C1/C2/C3",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_sec_grounding_prompt(
    project: dict[str, Any],
    hazard_row: dict[str, Any],
    scenario: dict[str, Any],
    sec: dict[str, Any],
) -> str:
    function_pattern = relevant_function_pattern(project, hazard_row)
    return (
        prompt_header("sec_grounding_review")
        + read_text(REF_DIR / "sec-guide.md")
        + ("\n\n## 当前功能族物理知识\n" + function_pattern if function_pattern else "")
        + "\n\n"
        + read_text(REF_DIR / "sec-grounding-audit.md")
        + "\n\n## HARA 评审反模式\n"
        + read_text(REF_DIR / "review-rules.md")
        + "\n\n## 只允许使用这一条场景事实和当前 SEC 草案\n"
        + json.dumps(
            {"project": project, "hazard": hazard_row, "scenario": scenario, "current_sec": sec},
            ensure_ascii=False,
            indent=2,
        )
        + "\n\n审计并返回最终 SEC。若当前 SEC 完全扎根于场景，可保持不变；若存在与场景不一致、补事实、模板化或评级不合理，必须基于本行事实重做。"
        + "不要输出审计过程之外的 Markdown。\n"
        + "\n\n输出 JSON schema：\n"
        + json.dumps(
            {
                "approved": True,
                "issues": [{"field": "E/S/C", "issue": "string", "scenario_evidence": "string"}],
                "final_sec": {
                    "E-解释": "string",
                    "暴露频率'E'": "E0/E1/E2/E3/E4",
                    "可能的后果('S'的理由)": "string",
                    "Severity 'S'": "S0/S1/S2/S3",
                    "C-解释": "string",
                    "控制能力 'C'": "C0/C1/C2/C3",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def asil(s: str, e: str, c: str) -> str:
    score = int(s[1]) + int(e[1]) + int(c[1])
    if "0" in (s[1], e[1], c[1]) or score <= 6:
        return "QM"
    return {7: "A", 8: "B", 9: "C"}.get(score, "D")


def canonical_sec(sec: dict[str, Any]) -> dict[str, str]:
    def compact_key(value: str) -> str:
        return re.sub(r"[\s'\"()（）:：\\-]", "", value).lower()

    def pick(canonical: str, aliases: list[str]) -> str:
        if canonical in sec:
            return str(sec[canonical]).strip()
        for alias in aliases:
            if alias in sec:
                return str(sec[alias]).strip()
        lowered = {compact_key(str(k)): v for k, v in sec.items()}
        for key in [canonical, *aliases]:
            lk = compact_key(key)
            if lk in lowered:
                return str(lowered[lk]).strip()
        for raw_key, value in sec.items():
            ck = compact_key(str(raw_key))
            if ck.startswith(compact_key(canonical)[:8]) or any(ck.startswith(compact_key(alias)[:8]) for alias in aliases):
                return str(value).strip()
        raise KeyError(f"SEC 输出缺少字段 {canonical}: {sec}")

    return {
        "E-解释": pick("E-解释", ["暴露解释", "E解释", "Exposure rationale", "Exposure 'E' rationale"]),
        "暴露频率'E'": pick("暴露频率'E'", ["暴露频率", "Exposure 'E'", "E"]),
        "可能的后果('S'的理由)": pick("可能的后果('S'的理由)", ["S-解释", "S解释", "Severity rationale", "可能的后果"]),
        "Severity 'S'": pick("Severity 'S'", ["Severity", "S", "严重度'S'", "严重度"]),
        "C-解释": pick("C-解释", ["控制能力解释", "C解释", "Controllability rationale"]),
        "控制能力 'C'": pick("控制能力 'C'", ["控制能力'C'", "Controllability 'C'", "Controllability", "C"]),
    }


ACTION_PAIRS = [
    ("打开", "关闭"),
    ("点亮", "熄灭"),
    ("拉起", "释放"),
    ("锁止", "解锁"),
    ("加速", "减速"),
    ("左", "右"),
    ("前进", "后退"),
    ("升高", "降低"),
    ("伸出", "收回"),
]


GUIDEWORD_COLUMNS = ["功能丧失", "过大", "过早", "过小", "过晚", "非预期激活", "卡滞", "方向错误"]
SCENARIO_FIELDS = [
    "道路类型",
    "道路条件",
    "环境条件",
    "车辆状态",
    "车速(km/h)",
    "特殊要素",
    "附加条件",
    "驾驶员是否在车上",
    "危害事件",
    "有风险的人员",
]


def fault_action_signature(value: str) -> str:
    body = re.sub(r"^MF\d{3,}(?:[.\-]\d+)?\s*", "", str(value)).strip()
    actions = [action for pair in ACTION_PAIRS for action in pair] + ["制动", "转向"]
    for action in actions:
        if action in body:
            return action
    return ""


def polish_fault_body(body: str, guideword: str) -> str:
    body = body.strip(" ，,。；;")
    if body.upper() in {"N/A", "NA"} or body in {"不适用", "无", "无此故障"}:
        return ""
    condition_prefixes = [
        r"^车辆静止时",
        r"^驻车时",
        r"^行驶中",
        r"^静止时",
        r"^低速时",
        r"^高速时",
        r"^未请求时",
        r"^无请求时",
        r"^不满足[^，,；;\s]{0,20}时",
        r"^车速[^，,；;\s]{0,20}时",
        r"^电源[^，,；;\s]{0,20}时",
        r"^休眠[^，,；;\s]{0,20}时",
        r"^网络[^，,；;\s]{0,20}时",
    ]
    for prefix in condition_prefixes:
        body = re.sub(prefix, "", body).strip()
    body = re.sub(r"^(.{1,30}?)应([^，,；;\s]{1,8})时无法\2$", r"\1无法\2", body)
    if guideword == "过晚":
        body = body.replace("响应延迟", "响应过晚")
        if body.endswith("延迟"):
            body = body[:-2] + "响应过晚"
    if guideword == "非预期激活" and body and "非预期" not in body:
        action = fault_action_signature(body)
        if action and action in body:
            body = body.replace(action, f"非预期{action}", 1)
    return body


def polish_fault_text(fault_text: str, guideword: str) -> str:
    match = re.match(r"^(MF\d{3,}(?:[.\-]\d+)?)\s*(.+)$", str(fault_text).strip())
    if not match:
        body = polish_fault_body(str(fault_text), guideword)
        return body
    code, body = match.groups()
    body = polish_fault_body(body, guideword)
    return f"{code} {body}" if body else ""


def expand_slash_fault_text(fault_text: str, guideword: str) -> list[str]:
    polished = polish_fault_text(fault_text, guideword)
    if not polished:
        return []
    match = re.match(r"^(MF\d{3,}(?:[.\-]\d+)?)\s*(.+)$", polished)
    if not match:
        return [polished]
    code, body = match.groups()
    for left, right in ACTION_PAIRS:
        marker = f"{left}/{right}"
        if marker in body:
            return [f"{code} {body.replace(marker, left)}", f"{code} {body.replace(marker, right)}"]
    return [polished]


def polish_fault_cell(cell: str, guideword: str) -> str:
    cell = str(cell or "").strip()
    if not cell or cell.upper() in {"N/A", "NA"} or cell in {"不适用", "无", "无此故障"}:
        return ""
    matches = list(re.finditer(r"MF\d{3,}(?:[.\-]\d+)?", cell))
    if not matches:
        return polish_fault_body(cell, guideword)
    polished = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cell)
        faults = expand_slash_fault_text(cell[start:end].strip(" ；;，,。"), guideword)
        polished.extend(faults)
    return "；".join(polished)


def split_fault_cell(cell: str) -> list[str]:
    cell = str(cell or "").strip()
    if not cell:
        return []
    matches = list(re.finditer(r"MF\d{3,}(?:[.\-]\d+)?", cell))
    if len(matches) > 1:
        faults = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cell)
            fault = cell[start:end].strip(" ；;，,。")
            if fault:
                faults.append(fault)
        return faults
    match = re.match(r"^(MF\d{3,}(?:[.\-]\d+)?)\s*(.+)$", cell)
    if not match:
        return [cell]
    code, body = match.groups()
    parts = re.split(r"\s*[；;]\s*", body.strip())
    return [f"{code} {part.strip(' ，,。')}" for part in parts if part.strip(" ，,。")]


def sheet1_fault_records(row: dict[str, str], split_faults: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use the normalized sheet1 row as the source of truth for sheet2 traceability."""
    metadata_by_fault = {str(item.get("fault", "")).strip(): item for item in split_faults if str(item.get("fault", "")).strip()}
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for guideword in GUIDEWORD_COLUMNS:
        for fault in split_fault_cell(row.get(guideword, "")):
            if fault in seen:
                continue
            seen.add(fault)
            record = dict(metadata_by_fault.get(fault, {}))
            record["fault"] = fault
            record["guideword"] = guideword
            record.setdefault("safety_relevance", "unknown - sheet2 必须保留该 sheet1 故障并由危害映射阶段判断")
            records.append(record)
    return records


def is_bidirectional_current_function(function_name: str, row_text: str, left: str, right: str) -> bool:
    if left not in row_text or right not in row_text:
        return False
    has_left = left in function_name
    has_right = right in function_name
    return has_left == has_right


def infer_loss_object(loss_cell: str, action: str) -> str:
    match = re.search(r"MF\d{3,}(?:[.\-]\d+)?\s*(.+?)无法" + re.escape(action), loss_cell)
    if match:
        return match.group(1).strip()
    match = re.search(r"MF\d{3,}(?:[.\-]\d+)?\s*([^\s；;，,。]{1,20})", loss_cell)
    return match.group(1).strip() if match else ""


def complete_bidirectional_loss(row: dict[str, str], function_name: str, split_faults: list[dict[str, Any]]) -> list[dict[str, Any]]:
    loss_cell = row.get("功能丧失", "")
    if not loss_cell:
        return split_faults
    row_text = " ".join(row.get(col, "") for col in GUIDEWORD_COLUMNS)
    code_match = re.search(r"MF\d{3,}(?:[.\-]\d+)?", loss_cell)
    if not code_match:
        return split_faults
    code = code_match.group(0)
    added_faults: list[str] = []
    for left, right in ACTION_PAIRS:
        if not is_bidirectional_current_function(function_name, row_text, left, right):
            continue
        has_left_loss = f"无法{left}" in loss_cell
        has_right_loss = f"无法{right}" in loss_cell
        if has_left_loss and not has_right_loss:
            obj = infer_loss_object(loss_cell, left)
            if obj:
                added_faults.append(f"{code} {obj}无法{right}")
        elif has_right_loss and not has_left_loss:
            obj = infer_loss_object(loss_cell, right)
            if obj:
                added_faults.append(f"{code} {obj}无法{left}")
    if added_faults:
        existing = set(part.strip() for part in re.split(r"[；;]", loss_cell) if part.strip())
        for fault in added_faults:
            if fault in existing:
                continue
            row["功能丧失"] = row["功能丧失"] + "；" + fault
            split_faults.append(
                {
                    "fault": fault,
                    "guideword": "功能丧失",
                    "safety_relevance": "yes - 双向状态控制功能的反向 required control action 未提供，需在后续 HARA 确认危害",
                }
            )
    return split_faults


def complete_bidirectional_unexpected(row: dict[str, str], function_name: str, split_faults: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unexpected_cell = row.get("非预期激活", "")
    if not unexpected_cell:
        return split_faults
    row_text = " ".join(row.get(col, "") for col in GUIDEWORD_COLUMNS)
    code_match = re.search(r"MF\d{3,}(?:[.\-]\d+)?", unexpected_cell)
    if not code_match:
        return split_faults
    code = code_match.group(0)
    added_faults: list[str] = []
    for left, right in ACTION_PAIRS:
        if not is_bidirectional_current_function(function_name, row_text, left, right):
            continue
        has_left = f"非预期{left}" in unexpected_cell
        has_right = f"非预期{right}" in unexpected_cell
        if has_left and not has_right:
            obj = re.search(r"MF\d{3,}(?:[.\-]\d+)?\s*(.+?)非预期" + re.escape(left), unexpected_cell)
            if obj:
                added_faults.append(f"{code} {obj.group(1).strip()}非预期{right}")
        elif has_right and not has_left:
            obj = re.search(r"MF\d{3,}(?:[.\-]\d+)?\s*(.+?)非预期" + re.escape(right), unexpected_cell)
            if obj:
                added_faults.append(f"{code} {obj.group(1).strip()}非预期{left}")
    existing = set(split_fault_cell(unexpected_cell))
    for fault in added_faults:
        if fault in existing:
            continue
        row["非预期激活"] = row["非预期激活"] + "；" + fault
        split_faults.append(
            {
                "fault": fault,
                "guideword": "非预期激活",
                "safety_relevance": "yes - 双向状态控制功能的反向非预期状态改变，需在后续 HARA 确认危害",
            }
        )
    return split_faults


def filter_non_core_sheet1_faults(
    row: dict[str, str], function_name: str, split_faults: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if any(term in function_name for term in ["报文", "提示", "报警", "显示", "反馈", "指示"]):
        return split_faults
    remove_terms = ["状态报文", "报文卡滞", "指示灯卡滞", "提示卡滞"]
    kept: list[dict[str, Any]] = []
    removed_faults: set[str] = set()
    for item in split_faults:
        fault = str(item.get("fault", "")).strip()
        if any(term in fault for term in remove_terms):
            removed_faults.add(fault)
            continue
        kept.append(item)
    if removed_faults:
        for guideword in GUIDEWORD_COLUMNS:
            faults = [fault for fault in split_fault_cell(row.get(guideword, "")) if fault not in removed_faults]
            row[guideword] = "；".join(faults)
    return kept


def complete_sheet2_rows(hazards: dict[str, Any], split_faults: list[dict[str, Any]]) -> dict[str, Any]:
    rows = list(hazards.get("mf_vehicle_hazards") or [])
    existing_faults = {str(row.get("故障描述", "")).strip() for row in rows if str(row.get("故障描述", "")).strip()}
    for fault in split_faults:
        fault_text = str(fault.get("fault", "")).strip()
        if not fault_text or fault_text in existing_faults:
            continue
        rows.append(
            {
                "No.": "",
                "Milf_ID": "",
                "故障描述": fault_text,
                "整车级危害": "无危害",
                "备注": (
                    "map_hazard 阶段未生成该 sheet1 故障的整车危害；为满足 sheet1->sheet2 全量追溯先保留为无危害，"
                    f"待工程师评审。guideword={fault.get('guideword', '')}; safety_relevance={fault.get('safety_relevance', '')}"
                ),
            }
        )
        existing_faults.add(fault_text)
    hazards["mf_vehicle_hazards"] = rows
    return hazards


def postprocess_sheet2_hazards(hazards: dict[str, Any]) -> dict[str, Any]:
    """Normalize common sheet2 hazard mapping mistakes without changing traceability."""
    rows = list(hazards.get("mf_vehicle_hazards") or [])
    for row in rows:
        fault = str(row.get("故障描述", "")).strip()
        if "EPB" in fault and any(term in fault for term in ["夹紧力过大", "制动力过大"]):
            row["整车级危害"] = "无危害"
            row["备注"] = "静态拉起请求下夹紧力/制动力过大主要影响制动器、卡钳、电机或机构寿命，不应偷换为EPB非预期拉起或非预期减速。"
        elif "近光灯无法点亮" in fault or "近光灯亮度过小" in fault or "近光灯卡滞在熄灭状态" in fault:
            row["整车级危害"] = "驾驶员视野丢失或者降低"
            row["备注"] = "仅在夜间、隧道、低照度且驾驶员未及时采取措施时形成视野降低危害；HARA需考虑驾驶员通常会在起步/傍晚开灯时发现异常，E/C可能较低。"
        elif "近光灯点亮响应过晚" in fault:
            row["整车级危害"] = "驾驶员视野丢失或者降低"
            row["备注"] = "点亮延迟只在低照度中短时间缺少必要照明时形成危害；若只是几秒延迟，HARA通常应考虑低暴露和可控性，常见场景可能为QM。"
        elif "近光灯非预期熄灭" in fault:
            row["整车级危害"] = "驾驶员视野丢失或者降低"
            row["备注"] = "夜间、隧道或低照度行驶中突然熄灭可导致驾驶员视野下降；HARA需结合是否突然发生、替代照明和反应时间判断。"
        elif "近光灯无法熄灭" in fault or "近光灯亮度过大" in fault or "近光灯卡滞在点亮状态" in fault:
            row["整车级危害"] = "其他驾驶员/行人误判"
            row["备注"] = "近光灯持续点亮或亮度偏高可能影响其他道路使用者判断，但不能等同于远光灯强眩目；HARA中通常应谨慎评估严重度和可控性。"
        elif "近光灯非预期点亮" in fault:
            row["整车级危害"] = "其他驾驶员/行人误判"
            row["备注"] = "白天通常无危害，但夜间、低照度、会车或复杂交通中可能影响其他道路使用者判断；影响通常弱于远光灯，HARA多为低ASIL或QM。"
        elif "近光灯请求点亮却熄灭" in fault:
            row["整车级危害"] = "驾驶员视野丢失或者降低"
            row["备注"] = "该故障是有请求时的方向错误，不等同于行驶中突然非预期熄灭；驾驶员通常更容易发现请求未达成并采取补救，HARA中E/C应谨慎降低。"
        elif "近光灯请求熄灭却点亮" in fault:
            row["整车级危害"] = "无危害"
            row["备注"] = "请求熄灭通常说明当前不需要近光灯；该方向错误不等同于非预期点亮，驾驶员容易发现并再次操作，通常无车辆级人身伤害风险。"
    hazards["mf_vehicle_hazards"] = rows
    return hazards


def normalize_derive_row(system: str, function_index: int, function_name: str, derive: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    row = {
        "No.": f"{system}_fc{function_index:02d}",
        "子功能": function_name,
        "功能丧失": "",
        "过大": "",
        "过早": "",
        "过小": "",
        "过晚": "",
        "非预期激活": "",
        "卡滞": "",
        "方向错误": "",
    }
    split_faults = derive.get("split_faults") or []
    by_guideword: dict[str, list[str]] = {}
    guideword_codes: dict[str, str] = {}
    next_guideword_idx = 1
    normalized_split_faults: list[dict[str, Any]] = []
    for idx, fault in enumerate(split_faults, 1):
        guideword = str(fault.get("guideword", "")).strip()
        if guideword not in row:
            continue
        fault_text = str(fault.get("fault", "")).strip()
        if not fault_text:
            continue
        if guideword not in guideword_codes:
            guideword_codes[guideword] = f"MF{function_index}{next_guideword_idx:02d}"
            next_guideword_idx += 1
        code = guideword_codes[guideword]
        fault_body = re.sub(r"^MF\d{3,}(?:[.\-]\d+)?\s*", "", fault_text).strip()
        expanded_faults = expand_slash_fault_text(f"{code} {fault_body}", guideword)
        for fault_text in expanded_faults:
            if not fault_text:
                continue
            normalized_fault = dict(fault)
            normalized_fault["fault"] = fault_text
            normalized_split_faults.append(normalized_fault)
            by_guideword.setdefault(guideword, []).append(fault_text)
    split_faults = normalized_split_faults
    if by_guideword:
        kept_fault_texts: set[str] = set()
        for guideword, faults in by_guideword.items():
            if guideword == "非预期激活":
                seen_actions: set[str] = set()
                unique_faults = []
                for fault in faults:
                    action = fault_action_signature(fault)
                    if action and action in seen_actions:
                        continue
                    if action:
                        seen_actions.add(action)
                    unique_faults.append(fault)
                faults = unique_faults
            kept_fault_texts.update(faults)
            row[guideword] = "；".join(faults)
        split_faults = [item for item in split_faults if str(item.get("fault", "")).strip() in kept_fault_texts]
        split_faults = complete_bidirectional_loss(row, function_name, split_faults)
        split_faults = complete_bidirectional_unexpected(row, function_name, split_faults)
        split_faults = filter_non_core_sheet1_faults(row, function_name, split_faults)
        return row, split_faults

    raw = derive.get("derive_mf_row") or {}
    for key in row:
        if key in raw:
            row[key] = str(raw.get(key) or "").strip()
    row["No."] = f"{system}_fc{function_index:02d}"
    row["子功能"] = function_name
    for guideword in GUIDEWORD_COLUMNS:
        row[guideword] = polish_fault_cell(row[guideword], guideword)
    split_faults = complete_bidirectional_loss(row, function_name, split_faults)
    split_faults = complete_bidirectional_unexpected(row, function_name, split_faults)
    split_faults = filter_non_core_sheet1_faults(row, function_name, split_faults)
    return row, split_faults


def highest_asil(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "QM"
    return max((str(row.get("结果ASIL", "QM")).upper() for row in rows), key=lambda x: ASIL_ORDER.get(x, 0))


def highest_asil_candidate(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    if not rows:
        return "QM", None
    candidate = max(rows, key=lambda r: ASIL_ORDER.get(str(r.get("结果ASIL", "QM")).upper(), 0))
    return str(candidate.get("结果ASIL", "QM")).upper(), candidate


def hara_rows_by_fault(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        fault = str(row.get("故障描述", "")).strip()
        grouped.setdefault(fault, []).append(row)
    return grouped


def fallback_safety_goal(row: dict[str, Any]) -> tuple[str, str]:
    hazard = str(row.get("整车危害", "")).strip()
    fault = re.sub(r"^MF\d{3,}\s*", "", str(row.get("故障描述", ""))).strip()
    if "视野" in hazard:
        return (
            f"防止{fault}导致驾驶员视野丢失或降低。",
            "近光灯提供必要照明；若无法提供，应及时告警并使驾驶员可进入安全停车状态。",
        )
    if "误判" in hazard:
        return (
            f"防止{fault}导致其他道路使用者误判本车状态。",
            "近光灯状态与驾驶员请求和车辆状态保持一致。",
        )
    if "报警" in hazard:
        return (
            f"防止{fault}导致驾驶员未及时获得必要报警。",
            "必要报警在规定时间内发出；无法报警时提供可识别降级提示。",
        )
    return (
        f"防止{fault}导致{hazard}。",
        "车辆保持或进入可控安全状态，并及时提示驾驶员。",
    )


def default_ftti(row: dict[str, Any]) -> str:
    asil_level = str(row.get("结果ASIL", "")).strip().upper()
    mode = operation_mode([row])
    return "100" if "行车" in mode and asil_level in {"C", "D"} else "500"


def build_fault_based_sg_sum(hara_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sg_sum: list[dict[str, Any]] = []
    for fault, rows in hara_rows_by_fault(hara_rows).items():
        max_asil, candidate = highest_asil_candidate(rows)
        if not candidate or max_asil == "QM":
            for row in rows:
                row["安全目标"] = ""
                row["安全状态"] = ""
                row["FTTI(ms)"] = ""
            continue
        goal = str(candidate.get("安全目标", "")).strip()
        safe_state = str(candidate.get("安全状态", "")).strip()
        if not goal or not safe_state:
            goal, safe_state = fallback_safety_goal(candidate)
        ftti = str(candidate.get("FTTI(ms)", "")).strip() or default_ftti(candidate)
        for row in rows:
            if str(row.get("结果ASIL", "QM")).upper() == "QM":
                row["安全目标"] = ""
                row["安全状态"] = ""
                row["FTTI(ms)"] = ""
            else:
                row["安全目标"] = goal
                row["安全状态"] = safe_state
                row["FTTI(ms)"] = ftti
        sg_sum.append(
            {
                "SG_No": f"SG{len(sg_sum) + 1:03d}",
                "安全目标": goal,
                "ASIL Level": max_asil,
                "安全状态": safe_state,
                "操作模式": operation_mode([candidate]),
                "FTTI(ms)": ftti,
            }
        )
    return sg_sum


def build_sg_input_groups(hara_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for fault, rows in hara_rows_by_fault(hara_rows).items():
        max_asil, candidate = highest_asil_candidate(rows)
        groups.append(
            {
                "故障描述": fault,
                "最高ASIL": max_asil,
                "是否生成SG": max_asil != "QM",
                "最高ASIL代表条目": candidate if max_asil != "QM" else None,
                "该故障HARA条目数": len(rows),
            }
        )
    return groups


def operation_mode(rows: list[dict[str, Any]]) -> str:
    states = {str(row.get("车辆状态", "")) for row in rows}
    parking = any(any(k in state for k in ["驻车", "停车", "泊车"]) for state in states)
    driving = any(state and not any(k in state for k in ["驻车", "停车", "泊车"]) for state in states)
    if parking and driving:
        return "驻车和行车"
    return "驻车" if parking else "行车"


def epb_sg_profile(fault: str) -> dict[str, str] | None:
    fault = re.sub(r"^MF\d{3,}\s*", "", str(fault or "")).strip()
    if "夹紧力过大" in fault:
        return None
    if "无法拉起" in fault and "卡滞" not in fault:
        return {
            "安全目标": "防止EPB无法按请求建立驻车保持力时车辆发生非预期纵向移动。",
            "安全状态": "车辆保持静止，或保持在驾驶员可通过常用制动控制的低速状态。",
        }
    if "夹紧力不足" in fault:
        return {
            "安全目标": "防止EPB驻车保持力不足导致车辆发生非预期纵向移动。",
            "安全状态": "车辆在预期驻车条件下保持静止，或保持在可控低速状态。",
        }
    if "响应过晚" in fault:
        return {
            "安全目标": "防止EPB驻车保持建立延迟期间车辆发生危险的非预期纵向移动。",
            "安全状态": "车辆在驻车保持建立前不产生危险位移，或保持在驾驶员可控制状态。",
        }
    if "非预期拉起" in fault:
        return {
            "安全目标": "防止EPB在行车或低速移动状态下非预期施加导致危险的非预期减速。",
            "安全状态": "车辆保持稳定行驶或以可控方式减速，不因EPB非预期施加产生失稳或追尾风险。",
        }
    if "卡滞在释放状态" in fault:
        return {
            "安全目标": "防止EPB卡滞释放导致车辆无法保持静止并发生非预期纵向移动。",
            "安全状态": "车辆保持静止，或保持在驾驶员可通过常用制动控制的低速状态。",
        }
    if "请求拉起却执行释放" in fault:
        return {
            "安全目标": "防止EPB请求驻车保持时反向释放导致车辆发生非预期纵向移动。",
            "安全状态": "车辆保持静止，或不因EPB反向释放产生危险位移。",
        }
    return None


def apply_epb_safety_goals(analysis: dict[str, Any], hara_rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    system_name = str(analysis.get("project", {}).get("system_name", "")).upper()
    if system_name != "EPB":
        return None

    rows_by_fault = hara_rows_by_fault(hara_rows)

    sg_sum: list[dict[str, Any]] = []
    sg_no = 1
    for hazard_row in analysis.get("mf_vehicle_hazards", []):
        fault = str(hazard_row.get("故障描述", "")).strip()
        hazard = str(hazard_row.get("整车级危害", "")).strip()
        if hazard == "无危害":
            continue
        profile = epb_sg_profile(fault)
        if not profile:
            continue
        rows = rows_by_fault.get(fault, [])
        asil_level, candidate = highest_asil_candidate(rows)
        if not candidate or asil_level == "QM":
            continue
        mode = operation_mode([candidate])
        ftti = "100" if "行车" in mode and asil_level in {"C", "D"} else "500"
        for row in rows:
            if str(row.get("结果ASIL", "QM")).upper() == "QM":
                row["安全目标"] = ""
                row["安全状态"] = ""
                row["FTTI(ms)"] = ""
            else:
                row["安全目标"] = profile["安全目标"]
                row["安全状态"] = profile["安全状态"]
                row["FTTI(ms)"] = ftti
        sg_sum.append(
            {
                "SG_No": f"SG{sg_no:03d}",
                "安全目标": profile["安全目标"],
                "ASIL Level": asil_level,
                "安全状态": profile["安全状态"],
                "操作模式": mode,
                "FTTI(ms)": ftti,
            }
        )
        sg_no += 1
    return sg_sum


def high_speed_vru_conflict(row: dict[str, Any]) -> bool:
    road = str(row.get("道路类型", ""))
    if road not in {"高速公路", "高速公路-上/下匝道", "城市快速路"}:
        return False
    scenario_text = " ".join(
        str(row.get(field, ""))
        for field in ["特殊要素", "附加条件", "危害事件", "有风险的人员", "可能的后果('S'的理由)", "C-解释"]
    )
    if not any(term in scenario_text for term in ["行人", "横穿马路", "自行车", "骑行者"]):
        return False
    allowed_context = ["施工区域", "事故场景", "服务区", "收费站", "应急车道", "路肩", "隧道养护", "故障处置", "救援"]
    return not any(term in scenario_text for term in allowed_context)


def normalize_high_speed_vru(row: dict[str, Any]) -> None:
    if not high_speed_vru_conflict(row):
        return
    fault = str(row.get("故障描述", ""))
    hazard = str(row.get("整车危害", ""))
    speed = str(row.get("车速(km/h)", ""))
    if "视野" in hazard:
        row["特殊要素"] = "在行驶道路上有被遗弃的货物或障碍物"
        row["有风险的人员"] = "本车驾驶员、前方车辆乘员"
        row["危害事件"] = "夜间高速/快速道路行驶时照明能力突然下降，驾驶员未能及时识别前方停驶车辆或遗落障碍物，导致追尾或撞击。"
        row["附加条件"] = "道路为封闭或快速通行道路，不采用弱势交通参与者横穿作为默认暴露对象；本场景以前方停驶车辆、遗落货物或障碍物作为视野不足后的危险对象。"
        row["可能的后果('S'的理由)"] = (
            f"车速{speed}下追尾前方停驶车辆或撞击遗落障碍物/护栏，可能导致本车乘员及前方车辆乘员严重骨折、头部损伤或内脏损伤等严重乃至危及生命的伤害。"
        )
        row["C-解释"] = (
            "高速/快速道路上近光灯突然熄灭后，驾驶员需要先感知视野下降再采取开启远光灯、制动或靠边等措施；"
            "前方车辆尾灯、反光标识或其他交通光源可提供部分线索，因此不默认完全不可控，但高车速下反应和制动距离仍明显受限。"
        )
    elif "误判" in hazard:
        if any(term in str(row.get("特殊要素", "")) for term in ["行人", "横穿马路", "自行车", "骑行者"]):
            row["特殊要素"] = "不涉及"
        risk = str(row.get("有风险的人员", ""))
        risk = risk.replace("和行人", "").replace("、行人", "").replace("行人和", "")
        row["有风险的人员"] = risk or "其他车辆驾驶员和乘员"
        for field in ["附加条件", "危害事件", "可能的后果('S'的理由)", "C-解释"]:
            value = str(row.get(field, ""))
            value = value.replace("其他道路使用者和行人", "其他车辆驾驶员和乘员")
            value = value.replace("其他车辆驾驶员和行人", "其他车辆驾驶员和乘员")
            value = value.replace("行人判断", "其他车辆驾驶员判断")
            value = value.replace("路边行人", "其他车辆驾驶员")
            row[field] = value


def normalize_unsupported_collision_branches(row: dict[str, Any]) -> None:
    scenario_text = " ".join(
        str(row.get(field, ""))
        for field in ["道路类型", "道路条件", "环境条件", "车辆状态", "车速(km/h)", "特殊要素", "附加条件", "危害事件", "有风险的人员"]
    )
    rear_end_supported = any(
        term in scenario_text
        for term in ["前车", "前方车辆", "慢行车辆", "停驶车辆", "与前车距离", "后车", "后方车辆", "后方排队车辆", "跟车距离", "交通堵塞", "临近拥堵"]
    )
    if rear_end_supported:
        return
    for field in ["危害事件", "可能的后果('S'的理由)"]:
        value = str(row.get(field, ""))
        value = value.replace("或追尾碰撞", "")
        value = value.replace("或追尾", "")
        value = value.replace("侧面碰撞，", "侧面碰撞，")
        row[field] = value


def normalize_epb_slope_direction(row: dict[str, Any]) -> None:
    if str(row.get("整车危害", "")) != "非预期的纵向移动":
        return
    fault = str(row.get("故障描述", ""))
    if "EPB" not in fault and "驻车" not in fault:
        return
    scenario_text = " ".join(
        str(row.get(field, ""))
        for field in ["道路条件", "特殊要素", "附加条件", "危害事件", "有风险的人员", "可能的后果('S'的理由)", "C-解释"]
    )
    road_condition = str(row.get("道路条件", ""))
    reverse_orientation = any(term in scenario_text for term in ["车头朝上坡", "车头朝坡上", "倒车方向", "倒车", "外力向后", "被前方车辆推动"])
    backward_terms = [
        "向后滑", "向后溜", "向后移", "向后移动", "后退", "后溜", "撞击后方", "撞上后方",
        "与后车", "后方行人", "后方车辆", "后方道路使用者", "后方障碍物", "侧后方行人"
    ]
    forward_terms = [
        "向前滑", "向前溜", "向前移", "向前移动", "前移", "前溜", "撞击前方", "撞上前方",
        "与前方车辆", "与前车", "前方行人", "前方车辆", "前车", "前方障碍物", "进入主路"
    ]
    # 对 EPB 纵向移动，优先让坡道枚举与危险事件中的前/后运动方向一致。
    # 驱动蠕行等相反力源可解释物理，但如果保留“上坡+向前/下坡+向后”会让评审表读起来像方向错误。
    if road_condition == "上坡道路" and any(term in scenario_text for term in forward_terms):
        row["道路条件"] = "下坡道路"
        road_condition = "下坡道路"
    elif road_condition == "下坡道路" and any(term in scenario_text for term in backward_terms) and not reverse_orientation:
        row["道路条件"] = "上坡道路"
        road_condition = "上坡道路"
    if road_condition == "下坡道路" and any(term in scenario_text for term in backward_terms) and not reverse_orientation:
        replacements = {
            "向后滑移": "向前滑移",
            "向后滑": "向前滑",
            "向后溜车": "向前溜车",
            "向后溜移": "向前溜移",
            "向后溜": "向前溜",
            "向后移动": "向前移动",
            "后退": "前移",
            "后方行人": "前方行人",
            "后方车辆": "前方车辆",
            "后方排队车辆": "前方排队车辆",
            "后方来车": "前方车辆",
            "后车乘员": "前车乘员",
            "后车": "前车",
            "与后车距离较近": "与前车距离较近",
        }
        for field in ["特殊要素", "附加条件", "危害事件", "有风险的人员", "可能的后果('S'的理由)", "C-解释"]:
            value = str(row.get(field, ""))
            for old, new in replacements.items():
                value = value.replace(old, new)
            row[field] = value
    elif road_condition == "上坡道路" and any(term in scenario_text for term in forward_terms):
        replacements = {
            "向前滑移": "向后滑移",
            "向前滑": "向后滑",
            "向前溜车": "向后溜车",
            "向前溜移": "向后溜移",
            "向前溜": "向后溜",
            "向前移动": "向后移动",
            "前移": "后退",
            "前方行人": "后方行人",
            "前方车辆": "后方车辆",
            "前方排队车辆": "后方排队车辆",
            "前方停驶车辆": "后方停驶车辆",
            "前车乘员": "后车乘员",
            "前车": "后车",
            "与前车距离较近": "与后车距离较近",
        }
        for field in ["特殊要素", "附加条件", "危害事件", "有风险的人员", "可能的后果('S'的理由)", "C-解释"]:
            value = str(row.get(field, ""))
            for old, new in replacements.items():
                value = value.replace(old, new)
            row[field] = value
    if row.get("特殊要素") == "与后车距离正常":
        row["特殊要素"] = "与后车距离较近"
    if road_condition == "下坡道路":
        replacements = {
            "撞击行人": "撞击前方行人",
            "附近行人": "前方附近行人",
            "道路上的行人": "前方行人",
            "附近行人": "前方附近行人",
            "附近其他道路使用者": "前方附近其他道路使用者",
            "后方来车乘员": "同向来车乘员",
            "后方来车": "同向来车",
        }
        for field in ["附加条件", "危害事件", "有风险的人员", "可能的后果('S'的理由)", "C-解释"]:
            value = str(row.get(field, ""))
            for old, new in replacements.items():
                value = value.replace(old, new)
            row[field] = value
    elif road_condition == "上坡道路":
        replacements = {
            "撞击行人": "撞击后方行人",
            "撞击障碍物": "撞击后方障碍物",
            "行人、障碍物或对向车辆": "后方行人、后方障碍物或后方车辆",
            "行人、对向来车乘员": "后方行人、后方车辆乘员",
            "追尾后方来车": "撞击后方车辆",
            "追尾后车": "撞击后车",
            "追尾后方车辆": "撞击后方车辆",
            "后方来车乘员": "后方车辆乘员",
            "后方来车": "后方车辆",
        }
        for field in ["附加条件", "危害事件", "有风险的人员", "可能的后果('S'的理由)", "C-解释"]:
            value = str(row.get(field, ""))
            for old, new in replacements.items():
                value = value.replace(old, new)
            row[field] = value
    for field in ["特殊要素", "附加条件", "危害事件", "有风险的人员", "可能的后果('S'的理由)", "C-解释"]:
        value = str(row.get(field, ""))
        value = value.replace("前方前方", "前方").replace("后方后方", "后方")
        value = value.replace("侧后方后方", "侧后方")
        row[field] = value


def normalize_scenario_before_sec(hazard_row: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    row = {
        "故障描述": hazard_row.get("故障描述", ""),
        "整车危害": hazard_row.get("整车级危害", hazard_row.get("整车危害", "")),
        **{field: scenario.get(field, "") for field in SCENARIO_FIELDS},
    }
    normalize_high_speed_vru(row)
    normalize_unsupported_collision_branches(row)
    normalize_epb_slope_direction(row)
    return {field: row.get(field, "") for field in SCENARIO_FIELDS}


def remove_unsupported_condition_mentions(row: dict[str, Any]) -> None:
    scenario_text = " ".join(
        str(row.get(field, ""))
        for field in ["道路类型", "道路条件", "环境条件", "车辆状态", "车速(km/h)", "特殊要素", "附加条件", "危害事件", "有风险的人员"]
    )
    unsupported_terms = []
    if str(row.get("特殊要素", "")) != "隧道" and "隧道" not in scenario_text:
        unsupported_terms.append("隧道")
    if str(row.get("环境条件", "")) != "夜间" and "夜间" not in scenario_text:
        unsupported_terms.append("夜间")
    if "傍晚" not in scenario_text and str(row.get("环境条件", "")) not in {"夜间"}:
        unsupported_terms.append("傍晚")
    if "起步" not in scenario_text:
        unsupported_terms.append("起步")
    if "无路灯" not in scenario_text and "路灯灭" not in scenario_text:
        unsupported_terms.append("无路灯")
    if not any(term in scenario_text for term in ["刚接手车辆", "接手车辆"]):
        unsupported_terms.append("刚接手车辆")
    if not any(term in scenario_text for term in ["误以为已开灯", "以为已开灯"]):
        unsupported_terms.append("误以为已开灯")
    if not any(term in scenario_text for term in ["前车距离较近", "与前车距离较近", "跟车距离较近"]):
        unsupported_terms.extend(["前车距离较近", "跟车距离较近"])
    if not unsupported_terms:
        return
    for field in ["E-解释", "可能的后果('S'的理由)", "C-解释"]:
        value = str(row.get(field, ""))
        if not value:
            continue
        parts = re.split(r"(?<=[。！？])", value)
        kept = [part for part in parts if part.strip() and not any(term in part for term in unsupported_terms)]
        if kept and len("".join(kept).strip()) >= 12:
            row[field] = "".join(kept).strip()
        elif any(term in value for term in unsupported_terms):
            row[field] = ""


def light_scene_summary(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("环境条件", "")).strip(),
        str(row.get("道路类型", "")).strip(),
        str(row.get("道路条件", "")).strip(),
        str(row.get("车辆状态", "")).strip(),
        str(row.get("车速(km/h)", "")).strip(),
    ]
    special = str(row.get("特殊要素", "")).strip()
    if special and special != "不涉及":
        parts.append(special)
    return "、".join(part for part in parts if part)


def light_scene_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(field, ""))
        for field in ["道路类型", "道路条件", "环境条件", "车辆状态", "车速(km/h)", "特殊要素", "附加条件", "危害事件", "有风险的人员"]
    )


def light_request_failure_reason(row: dict[str, Any]) -> tuple[str, str]:
    scene = light_scene_summary(row)
    text = light_scene_text(row)
    env = str(row.get("环境条件", "")).strip()
    if "起步" in text:
        e_reason = f"本行场景为{scene}，暴露按起步阶段驾驶员需要近光且请求未达成的短时间片段计算，不按全部行驶时间计算。"
    elif "傍晚" in text:
        e_reason = f"本行场景为{scene}，附加条件限定为傍晚光线减弱时近光请求未达成，属于低照度转换期的低概率子场景。"
    elif "隧道" in text:
        e_reason = f"本行场景为{scene}，暴露按隧道或照明突变环境中近光请求未达成、驾驶员识别前方目标受影响的子场景计算。"
    elif any(term in text for term in ["刚接手车辆", "误以为已开灯", "未及时发现近光", "未及时发现灯"]):
        e_reason = f"本行场景为{scene}，附加条件限定驾驶员未及时发现近光未点亮；该组合只是当前道路和环境中的低概率子场景，不按全部行驶时间计算。"
    elif env == "夜间":
        e_reason = f"本行场景为{scene}，暴露按夜间需要近光而请求未达成、且外部照明不足以完全补偿的子场景计算，不按全部夜间行驶时间计算。"
    elif env == "日间":
        e_reason = f"本行场景为{scene}，日间通常不依赖近光提供视野，暴露仅覆盖驾驶员仍请求近光或法规/识别需求要求点亮近光的有限片段。"
    else:
        e_reason = f"本行场景为{scene}，暴露按当前场景中需要近光且请求未达成的使用片段计算。"

    critical = any(term in text for term in ["未及时发现", "前车距离较近", "与前车距离较近", "障碍物", "施工", "隧道", "难以及时", "高速"])
    if critical:
        c_reason = "本行场景中近光未点亮会影响驾驶员识别前方目标；驾驶员仍可通过照明效果、仪表状态、前车灯光或路面反光发现异常并制动、减速、开启其他照明或靠边，但车速、距离或道路空间会限制反应时间。"
    else:
        c_reason = "驾驶员可通过前方照明效果、仪表状态或环境亮度感知近光未点亮，并可减速、停车或使用其他照明补救；本行场景未给出极短反应时间或空间完全不足的条件。"
    return e_reason, c_reason


def light_brightness_low_reason(row: dict[str, Any]) -> tuple[str, str]:
    scene = light_scene_summary(row)
    text = light_scene_text(row)
    env = str(row.get("环境条件", "")).strip()
    if env == "日间" and "隧道" not in text:
        e_reason = f"本行场景为{scene}，日间主要依靠环境光，暴露仅覆盖仍需要近光提供识别或法规可见性的有限片段。"
    elif "隧道" in text:
        e_reason = f"本行场景为{scene}，暴露按隧道内近光亮度不足、环境光变化且需要前照灯补偿的子场景计算，不按全部道路行驶时间计算。"
    elif env == "降雨(小/大/暴)":
        e_reason = f"本行场景为{scene}，暴露按降雨导致路面反光和能见度下降、近光亮度不足进一步缩短可视距离的子场景计算。"
    elif env == "夜间":
        e_reason = f"本行场景为{scene}，暴露按夜间近光亮度不足且外部照明不足以补偿的使用片段计算。"
    else:
        e_reason = f"本行场景为{scene}，暴露按当前环境下近光亮度不足会影响识别距离的使用片段计算。"
    if light_visibility_critical(row):
        c_reason = "本行场景中近光亮度不足会缩短驾驶员识别前方目标的距离；驾驶员可通过路面可见性下降、前车灯光或道路反光发现异常并减速、制动或靠边，但当前车速、距离、道路条件和可视距离会限制反应和制动余量。"
    else:
        c_reason = "亮度不足通常可通过照射距离和路面可见性被驾驶员发现，驾驶员可降低车速、靠边停车或切换补充照明；本行场景未给出极短反应时间或空间完全不足的条件。"
    return e_reason, c_reason


def sec_level_suffix(value: Any, prefix: str) -> int | None:
    value = str(value or "").strip().upper()
    if re.fullmatch(prefix + r"\d", value):
        return int(value[1])
    return None


def set_c_at_least(row: dict[str, Any], level: str) -> bool:
    current = sec_level_suffix(row.get("控制能力 'C'"), "C")
    target = int(level[1])
    if current is None or current < target:
        row["控制能力 'C'"] = level
        return True
    return False


def light_visibility_critical(row: dict[str, Any]) -> bool:
    text = light_scene_text(row)
    speed = str(row.get("车速(km/h)", "")).replace(",", "，")
    low_speed = speed in {"静止状态", "[0，10]", "(0，10]"} or "0，10" in speed
    return (not low_speed) and any(
        term in text
        for term in ["与前车距离较近", "前车距离较近", "障碍物", "施工", "隧道", "降雨", "暴雨", "浮水", "无路灯", "未及时", "难以及时"]
    )


def light_on_or_overbright_reason(row: dict[str, Any]) -> str:
    scene = light_scene_summary(row)
    env = str(row.get("环境条件", "")).strip()
    if env == "日间":
        return f"本行场景为{scene}，日间环境光充足，近光持续点亮或亮度偏大通常只在近距离交互或特殊识别需求中影响判断。"
    return f"本行场景为{scene}，暴露按其他交通参与者可见本车近光且可能发生短时位置、距离或意图误判的片段计算。"


def light_unexpected_extinguish_reason(row: dict[str, Any]) -> tuple[str, str]:
    scene = light_scene_summary(row)
    text = light_scene_text(row)
    env = str(row.get("环境条件", "")).strip()
    if env == "日间" and "隧道" not in text:
        e_reason = f"本行场景为{scene}，日间近光突然熄灭通常不影响驾驶员视野，暴露仅覆盖需要近光增强识别或提示的有限片段。"
    elif "隧道" in text:
        e_reason = f"本行场景为{scene}，暴露按隧道或照明突变环境中近光突然熄灭、驾驶员识别前方目标受影响的子场景计算。"
    elif env == "夜间":
        e_reason = f"本行场景为{scene}，暴露按夜间行驶中近光突然熄灭且前方识别需求较高的场景计算。"
    else:
        e_reason = f"本行场景为{scene}，暴露按当前环境中近光突然熄灭会影响驾驶员识别距离的使用片段计算。"
    c_reason = "近光突然熄灭会压缩驾驶员识别前方目标的时间；驾驶员仍可能借助车速控制、其他灯光、前车尾灯、道路反光标识或靠边空间进行部分补救。"
    return e_reason, c_reason


def align_lighting_sec_with_scene(row: dict[str, Any]) -> None:
    fault = str(row.get("故障描述", ""))
    if "近光灯" not in fault:
        return
    changed_sec = False
    if any(term in fault for term in ["无法点亮", "请求点亮却熄灭", "卡滞在熄灭状态"]):
        e_reason, c_reason = light_request_failure_reason(row)
        if not str(row.get("E-解释", "")).strip():
            row["E-解释"] = e_reason
        if not str(row.get("C-解释", "")).strip():
            row["C-解释"] = c_reason
    elif "亮度过小" in fault:
        e_reason, c_reason = light_brightness_low_reason(row)
        if not str(row.get("E-解释", "")).strip():
            row["E-解释"] = e_reason
        if light_visibility_critical(row):
            row["C-解释"] = c_reason
            changed_sec |= set_c_at_least(row, "C2")
        elif not str(row.get("C-解释", "")).strip():
            row["C-解释"] = c_reason
    elif "非预期熄灭" in fault:
        e_reason, c_reason = light_unexpected_extinguish_reason(row)
        if not str(row.get("E-解释", "")).strip():
            row["E-解释"] = e_reason
        if not str(row.get("C-解释", "")).strip():
            row["C-解释"] = c_reason
    elif any(term in fault for term in ["亮度过大", "无法熄灭", "非预期点亮", "卡滞在点亮状态", "请求熄灭却点亮"]):
        if not str(row.get("E-解释", "")).strip():
            row["E-解释"] = light_on_or_overbright_reason(row)
    if changed_sec and all(str(row.get(field, "")).strip() for field in ["Severity 'S'", "暴露频率'E'", "控制能力 'C'"]):
        row["结果ASIL"] = asil(str(row.get("Severity 'S'")), str(row.get("暴露频率'E'")), str(row.get("控制能力 'C'")))


def postprocess_analysis(analysis: dict[str, Any], system: str) -> dict[str, Any]:
    scenarios = json.loads(read_text(ASSET_DIR / "operation_scenarios.json"))
    special_allowed = set(scenarios.get("特殊要素", []))
    road_conditions = set(scenarios.get("道路条件", []))
    environments = set(scenarios.get("环境条件", []))
    speeds = set(scenarios.get("车速(km/h)", []))
    road_types = set(scenarios.get("道路类型", []))
    vehicle_states = set(scenarios.get("车辆状态", []))

    def split_tokens(value: str) -> list[str]:
        return [token.strip() for token in re.split(r"[;；,，、/]+", value) if token.strip()]

    def choose_allowed(value: str, allowed: set[str], default: str, prefer_slope: bool = False) -> str:
        value = str(value or "").strip()
        if value in allowed:
            return value
        aliases = {
            "夜晚路灯条件(灭)": "夜晚路灯条件(亮/暗/灭)",
            "夜晚路灯条件(暗)": "夜晚路灯条件(亮/暗/灭)",
            "夜晚路灯条件(亮)": "夜晚路灯条件(亮/暗/灭)",
            "行进路线上有被遗弃的货物或障碍物": "在行驶道路上有被遗弃的货物或障碍物",
            "行人数量(中)": "行人数量(少)",
            "进入隧道": "隧道",
        }
        if value in aliases and aliases[value] in allowed:
            return aliases[value]
        tokens = split_tokens(value)
        normalized = [aliases.get(token, token) for token in tokens]
        if prefer_slope:
            for token in normalized:
                if token in {"上坡道路", "下坡道路"} and token in allowed:
                    return token
        for token in normalized:
            if token in allowed:
                return token
        for token in normalized:
            if token == "行人数量(中)" and "行人数量(少)" in allowed:
                return "行人数量(少)"
        return default

    for idx, row in enumerate(analysis.get("mf_vehicle_hazards", []), 1):
        row["No."] = idx
        row["Milf_ID"] = f"{system}_Milf_{idx:03d}"

    cleaned_hara: list[dict[str, Any]] = []
    for row in analysis.get("HARA", []):
        if not str(row.get("危害事件", "")).strip():
            continue
        road_condition = str(row.get("道路条件", "")).strip()
        environment = str(row.get("环境条件", "")).strip()
        speed = str(row.get("车速(km/h)", "")).strip()
        special = str(row.get("特殊要素", "")).strip()
        vehicle_state = str(row.get("车辆状态", "")).strip()
        row["道路类型"] = choose_allowed(str(row.get("道路类型", "")), road_types, "不涉及")
        if road_condition not in road_conditions and road_condition in special_allowed:
            row["特殊要素"] = road_condition
            row["道路条件"] = "直道"
        elif road_condition not in road_conditions and road_condition in {"双向两车道", "单向两车道"}:
            row["道路条件"] = "直道"
        elif road_condition not in road_conditions:
            row["道路条件"] = choose_allowed(
                road_condition,
                road_conditions,
                "直道",
                prefer_slope=str(row.get("整车危害", "")) == "非预期的纵向移动",
            )
        if environment == "降雨(大/暴)" or environment == "降雨":
            row["环境条件"] = "降雨(小/大/暴)"
        elif environment == "降雪(大/暴)" or environment == "降雪":
            row["环境条件"] = "降雪(小/大/暴)"
        elif environment not in environments and "隧道" in str(row.get("附加条件", "")):
            row["环境条件"] = "日间" if "日间" in environment else "夜间"
        elif environment not in environments:
            row["环境条件"] = choose_allowed(environment, environments, "不涉及")
        scenario_text = " ".join(
            str(row.get(field, ""))
            for field in ["道路条件", "环境条件", "特殊要素", "附加条件", "危害事件", "E-解释", "可能的后果('S'的理由)", "C-解释"]
        )
        if row.get("环境条件") in {"不涉及", "ALL", ""}:
            if any(term in scenario_text for term in ["暴雨", "大雨", "降雨", "雨天", "雨后", "积水", "湿滑", "浮水"]):
                row["环境条件"] = "降雨(小/大/暴)"
            elif any(term in scenario_text for term in ["暴雪", "大雪", "降雪", "雪天"]):
                row["环境条件"] = "降雪(小/大/暴)"
            elif "雾" in scenario_text:
                row["环境条件"] = "雾霾"
        if speed and speed not in speeds:
            normalized_speed = speed.replace(",", "，")
            if normalized_speed in speeds:
                row["车速(km/h)"] = normalized_speed
            else:
                row["车速(km/h)"] = choose_allowed(normalized_speed, speeds, "不涉及")
        if vehicle_state == "前向行驶":
            row["车辆状态"] = "前向匀速"
        elif vehicle_state not in vehicle_states:
            row["车辆状态"] = choose_allowed(vehicle_state, vehicle_states, "前向匀速")
        moving_states = {
            "前向加速",
            "前向匀速",
            "前向减速/刹车",
            "前向滑行",
            "后向行驶",
            "转弯(左转/右转)",
            "变道",
            "变道-紧急避让",
            "超车",
            "调头",
            "自动巡航",
            "智能领航",
        }
        if row.get("车速(km/h)") == "静止状态" and row.get("车辆状态") in moving_states:
            row["车辆状态"] = "停车未熄火"
        if special == "进入隧道":
            row["特殊要素"] = "隧道"
        elif special not in special_allowed:
            row["特殊要素"] = choose_allowed(special, special_allowed, "不涉及")
        if row.get("特殊要素") in {"不涉及", "ALL", ""} and "隧道" in scenario_text and "隧道" in special_allowed:
            row["特殊要素"] = "隧道"
        if str(row.get("整车危害", "")) == "非预期的纵向移动":
            extra = str(row.get("附加条件", ""))
            if row.get("道路条件") not in {"上坡道路", "下坡道路"} and not any(k in extra for k in ["坡", "蠕行", "外力", "驱动扭矩"]):
                row["道路条件"] = "下坡道路"
                row["附加条件"] = (extra + "；存在坡度或车辆蠕行趋势作为纵向移动来源。").strip("；")
        event = str(row.get("危害事件", "")).strip()
        if event and not any(k in event for k in ["导致", "造成", "引起", "碰撞", "追尾", "撞击", "伤害", "失控", "视野", "误判"]):
            row["危害事件"] = event + "，导致人员伤害风险。"
        cleaned_hara.append(row)

    for idx, row in enumerate(cleaned_hara, 1):
        row["List_No"] = idx
        row["MF_ID"] = f"{system}_MF_{idx:02d}"
        if not str(row.get("驾驶员是否在车上", "")).strip():
            state = str(row.get("车辆状态", ""))
            row["驾驶员是否在车上"] = "否" if any(k in state for k in ["停车熄火", "驻车"]) else "是"
        normalize_high_speed_vru(row)
        normalize_unsupported_collision_branches(row)
        normalize_epb_slope_direction(row)
        normalize_epb_slope_direction(row)
        remove_unsupported_condition_mentions(row)
        align_lighting_sec_with_scene(row)
        if str(row.get("Severity 'S'")) == "S0":
            event = str(row.get("危害事件", "")).strip()
            event = re.sub(r"[，,]?导致人员伤害风险。?", "，不构成安全相关危险事件，无人员伤害风险。", event)
            event = re.sub(r"[，,]?造成人员伤害风险。?", "，不构成安全相关危险事件，无人员伤害风险。", event)
            row["危害事件"] = event
        if row.get("结果ASIL") == "QM":
            row["安全目标"] = ""
            row["安全状态"] = ""
            row["FTTI(ms)"] = ""
        else:
            if not str(row.get("安全目标", "")).strip():
                goal, safe_state = fallback_safety_goal(row)
                row["安全目标"] = goal
                row["安全状态"] = safe_state
            if not str(row.get("安全状态", "")).strip():
                row["安全状态"] = "车辆保持或进入可控安全状态，并及时提示驾驶员。"
            if not str(row.get("FTTI(ms)", "")).strip():
                row["FTTI(ms)"] = default_ftti(row)

    analysis["HARA"] = cleaned_hara

    epb_sg_sum = apply_epb_safety_goals(analysis, cleaned_hara)
    if epb_sg_sum is not None:
        analysis["sg_sum"] = epb_sg_sum
        return analysis

    analysis["sg_sum"] = build_fault_based_sg_sum(cleaned_hara)
    return analysis


def build_sg_prompt(project: dict[str, Any], hara_rows: list[dict[str, Any]]) -> str:
    sg_groups = build_sg_input_groups(hara_rows)
    return (
        prompt_header("safety_goal")
        + read_text(REF_DIR / "hara-core.md")
        + "\n\n"
        + read_text(REF_DIR / "output-contract.md")
        + "\n\n## 按 MF 分组的安全目标输入\n"
        + json.dumps(sg_groups, ensure_ascii=False, indent=2)
        + "\n\n要求：每个故障 MF 只看本组 `最高ASIL代表条目` 生成一条 SG；`最高ASIL` 为 `QM` 或 `是否生成SG=false` 的故障不得生成 SG。"
        + "\n不要因为两个故障的安全目标文字相似而跨 MF 合并；`sg_sum` 的行数必须等于 `是否生成SG=true` 的故障数量。"
        + "\nupdates 中只需要覆盖非 QM HARA 行；同一故障 MF 的非 QM 行使用该 MF 最高 ASIL 代表条目的安全目标、安全状态和 FTTI。"
        + "\n\n输出 JSON schema：\n"
        + json.dumps(
            {
                "updates": [
                    {
                        "MF_ID": "SYS_MF_01",
                        "安全目标": "车辆级安全目标",
                        "安全状态": "车辆级安全状态",
                        "FTTI(ms)": "数字",
                    }
                ],
                "sg_sum": [
                    {"SG_No": "SG001", "安全目标": "string", "ASIL Level": "A/B/C/D", "安全状态": "string", "操作模式": "驻车/行车/驻车和行车", "FTTI(ms)": "数字"}
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_review_repair_prompt(project: dict[str, Any], review_text: str, rows: list[dict[str, Any]]) -> str:
    return (
        prompt_header("review_repair")
        + read_text(REF_DIR / "sec-guide.md")
        + "\n\n"
        + read_text(REF_DIR / "sec-grounding-audit.md")
        + "\n\n"
        + read_text(REF_DIR / "review-rules.md")
        + "\n\n## 功能族物理知识\n"
        + read_text(REF_DIR / "function-patterns.md")
        + "\n\n## project\n"
        + json.dumps(project, ensure_ascii=False, indent=2)
        + "\n\n## 工具评审 finding\n"
        + review_text
        + "\n\n## 只允许修订这些 HARA 行\n"
        + json.dumps(rows, ensure_ascii=False, indent=2)
        + "\n\n根据 finding 修订对应行。不要按模板改答案；必须基于每行场景事实、功能物理机制和评审规则重新判断。"
        + "如果 finding 是误报，也可以保持原值，但必须在 review_notes 说明为什么。"
        + "但如果 finding 指出解释文字包含场景字段未体现的条件，例如隧道、行人、对向来车、雨雪、坡道等，不能简单判为误报；"
        + "必须删除该无依据条件，或把场景枚举改成与文字一致。"
        + "即使该条件只是作为举例、对比或'通常发生在...'出现，也属于向 SEC 解释注入了本行没有的场景事实，必须移除。"
        + "允许修订场景字段、E/S/C 解释和等级；不得修改 List_No、MF_ID、故障描述、整车危害。"
        + "输出的每个 update 必须是完整的待覆盖字段集合；未列出的字段保持不变。\n"
        + "\n\n输出 JSON schema：\n"
        + json.dumps(
            {
                "updates": [
                    {
                        "List_No": 1,
                        "道路类型": "可选",
                        "道路条件": "可选",
                        "环境条件": "可选",
                        "车辆状态": "可选",
                        "车速(km/h)": "可选",
                        "特殊要素": "可选",
                        "附加条件": "可选",
                        "驾驶员是否在车上": "可选",
                        "危害事件": "可选",
                        "有风险的人员": "可选",
                        "E-解释": "string",
                        "暴露频率'E'": "E0/E1/E2/E3/E4",
                        "可能的后果('S'的理由)": "string",
                        "Severity 'S'": "S0/S1/S2/S3",
                        "C-解释": "string",
                        "控制能力 'C'": "C0/C1/C2/C3",
                        "review_notes": "string",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def run_validate_report(analysis_path: Path, cwd: Path, min_scenarios: int) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(HARA_TOOL), "validate", "--analysis", str(analysis_path), "--min-scenarios", str(min_scenarios)],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def warning_or_blocking_count(review_text: str, label: str) -> int:
    match = re.search(rf"{label}：(\d+)", review_text)
    return int(match.group(1)) if match else 0


def hara_list_numbers_from_review(review_text: str) -> list[int]:
    return sorted({int(value) for value in re.findall(r"HARA\[(\d+)\]", review_text)})


def apply_review_repair_updates(analysis: dict[str, Any], updates: list[dict[str, Any]]) -> bool:
    if not updates:
        return False
    rows = {int(row.get("List_No", 0)): row for row in analysis.get("HARA", []) if str(row.get("List_No", "")).isdigit()}
    allowed = set(SCENARIO_FIELDS) | {
        "E-解释",
        "暴露频率'E'",
        "可能的后果('S'的理由)",
        "Severity 'S'",
        "C-解释",
        "控制能力 'C'",
    }
    changed = False
    for update in updates:
        try:
            list_no = int(update.get("List_No", 0))
        except (TypeError, ValueError):
            continue
        row = rows.get(list_no)
        if not row:
            continue
        for key, value in update.items():
            if key in allowed and value not in (None, "", "可选"):
                row[key] = str(value).strip()
                changed = True
        if all(str(row.get(field, "")).strip() for field in ["Severity 'S'", "暴露频率'E'", "控制能力 'C'"]):
            row["结果ASIL"] = asil(str(row.get("Severity 'S'")), str(row.get("暴露频率'E'")), str(row.get("控制能力 'C'")))
    return changed


def maybe_repair_analysis(
    analysis: dict[str, Any],
    analysis_path: Path,
    stages: Path,
    claude_bin: str,
    cwd: Path,
    max_budget: str | None,
    min_scenarios: int,
) -> dict[str, Any]:
    for repair_round in range(1, 3):
        write_json(analysis_path, analysis)
        code, review_text = run_validate_report(analysis_path, cwd, min_scenarios)
        list_numbers = hara_list_numbers_from_review(review_text)
        if not list_numbers:
            return analysis
        rows = [row for row in analysis.get("HARA", []) if int(row.get("List_No", 0)) in set(list_numbers)]
        repair_prompt = stages / f"70_review_repair_round{repair_round}.prompt.md"
        write_text(repair_prompt, build_review_repair_prompt(analysis.get("project", {}), review_text, rows))
        repair = get_stage_json(stages / f"70_review_repair_round{repair_round}.json", repair_prompt, claude_bin, cwd, max_budget, resume=False)
        if not apply_review_repair_updates(analysis, repair.get("updates", []) if isinstance(repair, dict) else []):
            return analysis
        # Safety goals depend on ASIL after repair; regenerate them instead of patching stale goals.
        sg_prompt = stages / f"71_safety_goal_after_repair_round{repair_round}.prompt.md"
        write_text(sg_prompt, build_sg_prompt(analysis.get("project", {}), analysis.get("HARA", [])))
        goals = get_stage_json(stages / f"71_safety_goal_after_repair_round{repair_round}.json", sg_prompt, claude_bin, cwd, max_budget, resume=False)
        updates = {u["MF_ID"]: u for u in goals.get("updates", [])}
        for row in analysis.get("HARA", []):
            if row.get("结果ASIL") == "QM":
                row["安全目标"] = ""
                row["安全状态"] = ""
                row["FTTI(ms)"] = ""
                continue
            update = updates.get(row["MF_ID"])
            if update:
                row["安全目标"] = update.get("安全目标", "")
                row["安全状态"] = update.get("安全状态", "")
                row["FTTI(ms)"] = update.get("FTTI(ms)", "")
        analysis["sg_sum"] = goals.get("sg_sum") or []
        analysis = postprocess_analysis(analysis, str(analysis.get("project", {}).get("system_name", "")))
    return analysis


def install_skill(args: argparse.Namespace) -> int:
    target_root = Path(args.target) if args.target else Path.home() / ".claude" / "skills"
    target = target_root / "hara-analysis"
    target.mkdir(parents=True, exist_ok=True)
    for path in SKILL_DIR.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SKILL_DIR)
        dest = target / rel
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    print(f"installed hara-analysis skill to {target}")
    return 0


def run_pipeline(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    out = Path(args.out)
    source = Path(args.source)
    stages = out / "stages"
    out.mkdir(parents=True, exist_ok=True)
    stages.mkdir(parents=True, exist_ok=True)

    shell([sys.executable, str(HARA_TOOL), "init", "--source", str(source), "--out", str(out), "--system", args.system, "--force"], cwd)
    shell([sys.executable, str(HARA_TOOL), "extract-docx", "--source", str(source), "--out", str(out / "source")], cwd)

    source_md = read_text(out / "source" / "source.md")
    function_catalog = read_json(out / "source" / "function_catalog.json")
    claude_bin = find_claude(args.claude_bin)

    item_prompt = build_item_prompt(source_md, function_catalog, args.system)
    item_prompt_path = stages / "00_item_functions.prompt.md"
    write_text(item_prompt_path, item_prompt)
    if args.dry_run_prompts:
        print(f"wrote {item_prompt_path}")
        for fn in function_catalog.get("functions", []):
            name = fn["name"]
            derive_prompt_path = stages / f"10_derive_mf_{name}.prompt.md"
            write_text(derive_prompt_path, build_derive_prompt({"project": {"system_name": args.system}}, name, source_excerpt(source_md, name)))
            print(f"wrote {derive_prompt_path}")
        return 0

    item = get_stage_json(stages / "00_item_functions.json", item_prompt_path, claude_bin, cwd, args.max_budget, args.resume_existing)
    project = item["project"]
    derive_rows: list[dict[str, Any]] = []
    all_split_faults: list[dict[str, Any]] = []

    for index, function_name in enumerate(project.get("source_functions") or [], 1):
        prompt_path = stages / f"10_derive_mf_{index:02d}.prompt.md"
        write_text(prompt_path, build_derive_prompt(item, function_name, source_excerpt(source_md, function_name)))
        derive = get_stage_json(stages / f"10_derive_mf_{index:02d}.json", prompt_path, claude_bin, cwd, args.max_budget, args.resume_existing)
        row, split_faults = normalize_derive_row(args.system, index, function_name, derive)
        split_faults = sheet1_fault_records(row, split_faults)
        derive_rows.append(row)
        for item in split_faults:
            item["function_name"] = function_name
            item["function_index"] = index
        all_split_faults.extend(split_faults)

    if args.stop_after == "derive_mf":
        analysis = {
            "project": project,
            "derive_mf": derive_rows,
            "mf_vehicle_hazards": [],
            "HARA": [],
            "sg_sum": [],
        }
        analysis_path = out / "analysis_sheet1.json"
        write_json(analysis_path, analysis)
        shell(
            [
                sys.executable,
                str(HARA_TOOL),
                "export",
                "--analysis",
                str(analysis_path),
                "--out",
                str(out / "derive_mf.xlsx"),
                "--review-out",
                str(out / "review_sheet1.md"),
                "--min-scenarios",
                str(args.min_scenarios),
                "--skip-sheet2-completeness",
            ],
            cwd,
        )
        print(f"stopped after derive_mf: {analysis_path}")
        return 0

    hazard_prompt_path = stages / "20_hazard.prompt.md"
    write_text(hazard_prompt_path, build_hazard_prompt_from_faults(project, all_split_faults))
    hazards = get_stage_json(stages / "20_hazard.json", hazard_prompt_path, claude_bin, cwd, args.max_budget, args.resume_existing)
    hazards = complete_sheet2_rows(hazards, all_split_faults)
    hazards = postprocess_sheet2_hazards(hazards)

    if args.stop_after in {"sheet2", "mf_vehicle_hazards", "map_hazard"}:
        analysis = {
            "project": project,
            "derive_mf": derive_rows,
            "mf_vehicle_hazards": hazards.get("mf_vehicle_hazards") or [],
            "HARA": [],
            "sg_sum": [],
        }
        analysis = postprocess_analysis(analysis, args.system)
        analysis_path = out / "analysis_sheet2.json"
        write_json(analysis_path, analysis)
        shell(
            [
                sys.executable,
                str(HARA_TOOL),
                "export",
                "--analysis",
                str(analysis_path),
                "--out",
                str(out / "sheet2.xlsx"),
                "--review-out",
                str(out / "review_sheet2.md"),
                "--min-scenarios",
                str(args.min_scenarios),
                "--skip-scenario-coverage",
            ],
            cwd,
        )
        print(f"stopped after sheet2: {analysis_path}")
        return 0

    hara_rows: list[dict[str, Any]] = []
    list_no = 1
    for hazard_index, hazard_row in enumerate(hazards.get("mf_vehicle_hazards") or [], 1):
        if str(hazard_row.get("整车级危害", "")).strip() == "无危害":
            continue
        function_name = next((row["子功能"] for row in derive_rows if hazard_row.get("故障描述", "").startswith("MF" + str(derive_rows.index(row) + 1))), "")
        excerpt = source_excerpt(source_md, function_name or project.get("source_functions", [""])[0])
        scenario_prompt = stages / f"30_scenario_{hazard_index:03d}.prompt.md"
        write_text(scenario_prompt, build_scenario_prompt(project, hazard_row, excerpt, args.min_scenarios))
        candidates = get_stage_json(stages / f"30_scenario_{hazard_index:03d}.json", scenario_prompt, claude_bin, cwd, args.max_budget, args.resume_existing)

        review_prompt = stages / f"40_scenario_review_{hazard_index:03d}.prompt.md"
        write_text(review_prompt, build_scenario_review_prompt(hazard_row, candidates, args.min_scenarios))
        reviewed = get_stage_json(stages / f"40_scenario_review_{hazard_index:03d}.json", review_prompt, claude_bin, cwd, args.max_budget, args.resume_existing)

        for scenario_index, scenario in enumerate(reviewed.get("accepted") or [], 1):
            scenario = normalize_scenario_before_sec(hazard_row, scenario)
            sec_prompt = stages / f"50_sec_{hazard_index:03d}_{scenario_index:02d}.prompt.md"
            write_text(sec_prompt, build_sec_prompt(project, hazard_row, scenario))
            sec = get_stage_json(stages / f"50_sec_{hazard_index:03d}_{scenario_index:02d}.json", sec_prompt, claude_bin, cwd, args.max_budget, args.resume_existing)
            sec = canonical_sec(sec)
            sec_review_prompt = stages / f"55_sec_grounding_{hazard_index:03d}_{scenario_index:02d}.prompt.md"
            write_text(sec_review_prompt, build_sec_grounding_prompt(project, hazard_row, scenario, sec))
            sec_review = get_stage_json(
                stages / f"55_sec_grounding_{hazard_index:03d}_{scenario_index:02d}.json",
                sec_review_prompt,
                claude_bin,
                cwd,
                args.max_budget,
                args.resume_existing,
            )
            if isinstance(sec_review, dict) and isinstance(sec_review.get("final_sec"), dict):
                sec = canonical_sec(sec_review["final_sec"])
            level = asil(sec["Severity 'S'"], sec["暴露频率'E'"], sec["控制能力 'C'"])
            hara_rows.append(
                {
                    "List_No": list_no,
                    "MF_ID": f"{args.system}_MF_{list_no:02d}",
                    "故障描述": hazard_row["故障描述"],
                    "整车危害": hazard_row["整车级危害"],
                    **{k: scenario.get(k, "") for k in ["道路类型", "道路条件", "环境条件", "车辆状态", "车速(km/h)", "特殊要素", "附加条件", "驾驶员是否在车上", "危害事件", "有风险的人员"]},
                    **sec,
                    "结果ASIL": level,
                    "安全目标": "",
                    "安全状态": "",
                    "FTTI(ms)": "",
                }
            )
            list_no += 1

    sg_prompt = stages / "60_safety_goal.prompt.md"
    write_text(sg_prompt, build_sg_prompt(project, hara_rows))
    goals = get_stage_json(stages / "60_safety_goal.json", sg_prompt, claude_bin, cwd, args.max_budget, args.resume_existing)
    updates = {u["MF_ID"]: u for u in goals.get("updates", [])}
    for row in hara_rows:
        update = updates.get(row["MF_ID"])
        if update and row["结果ASIL"] != "QM":
            row["安全目标"] = update.get("安全目标", "")
            row["安全状态"] = update.get("安全状态", "")
            row["FTTI(ms)"] = update.get("FTTI(ms)", "")

    analysis = {
        "project": project,
        "derive_mf": derive_rows,
        "mf_vehicle_hazards": hazards.get("mf_vehicle_hazards") or [],
        "HARA": hara_rows,
        "sg_sum": goals.get("sg_sum") or [],
    }
    analysis = postprocess_analysis(analysis, args.system)
    analysis_path = out / "analysis.json"
    write_json(analysis_path, analysis)
    analysis = maybe_repair_analysis(
        analysis,
        analysis_path,
        stages,
        claude_bin,
        cwd,
        args.max_budget,
        args.min_scenarios,
    )
    write_json(analysis_path, analysis)
    shell([sys.executable, str(HARA_TOOL), "validate", "--analysis", str(analysis_path), "--min-scenarios", str(args.min_scenarios)], cwd)
    shell(
        [
            sys.executable,
            str(HARA_TOOL),
            "export",
            "--analysis",
            str(analysis_path),
            "--out",
            str(out / f"{args.system.lower()}_hara.xlsx"),
            "--review-out",
            str(out / "review.md"),
            "--min-scenarios",
            str(args.min_scenarios),
        ],
        cwd,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated Claude HARA pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--source", required=True)
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--system", required=True)
    p_run.add_argument("--min-scenarios", type=int, default=3)
    p_run.add_argument("--claude-bin")
    p_run.add_argument("--max-budget", default="8")
    p_run.add_argument("--dry-run-prompts", action="store_true")
    p_run.add_argument("--resume-existing", action="store_true")
    p_run.add_argument("--stop-after", choices=["derive_mf", "sheet2", "mf_vehicle_hazards", "map_hazard"])
    p_run.set_defaults(func=run_pipeline)

    p_install = sub.add_parser("install")
    p_install.add_argument("--target")
    p_install.set_defaults(func=install_skill)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
