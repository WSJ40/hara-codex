import importlib.util
import json
from pathlib import Path


path = Path("work/epb_hara_claude/analysis.json")
analysis = json.loads(path.read_text(encoding="utf-8"))

analysis["derive_mf"] = [
    {
        "No.": "EPB_fc01",
        "子功能": "静态开关拉起",
        "功能丧失": "MF101 车辆静止且EPB处于Released状态时驾驶员拉起EPB开关后未执行拉起；MF101 整车OFF或网络休眠状态下拉起EPB开关后系统未唤醒且未执行拉起",
        "过大": "",
        "过早": "",
        "过小": "MF102 EPB执行拉起但夹紧力不足，无法保持车辆驻车",
        "过晚": "MF103 EPB拉起响应延迟，车辆在驻车力建立前移动",
        "非预期激活": "MF104 EPB在无驾驶员拉起请求或车速超过静态门限时非预期拉起",
        "卡滞": "MF105 EPB卡滞在释放状态无法拉起",
        "方向错误": "",
    }
]

fault_map = {
    "MF101 请求拉起时EPB完全不拉起": "MF101 车辆静止且EPB处于Released状态时驾驶员拉起EPB开关后未执行拉起",
    "MF101 网络休眠唤醒失败": "MF101 整车OFF或网络休眠状态下拉起EPB开关后系统未唤醒且未执行拉起",
    "MF101 拉起后无法保持驻车状态": "MF102 EPB执行拉起但夹紧力不足，无法保持车辆驻车",
    "MF103 夹紧力不足": "MF102 EPB执行拉起但夹紧力不足，无法保持车辆驻车",
    "MF104 拉起响应延迟": "MF103 EPB拉起响应延迟，车辆在驻车力建立前移动",
    "MF105 未请求时非预期拉起": "MF104 EPB在无驾驶员拉起请求或车速超过静态门限时非预期拉起",
    "MF106 EPB状态卡滞": "MF105 EPB卡滞在释放状态无法拉起",
}

new_hara = []
for row in analysis["HARA"]:
    old_fault = row.get("故障描述", "")
    if old_fault == "MF102 夹紧力过大":
        continue
    if old_fault in fault_map:
        row["故障描述"] = fault_map[old_fault]
    if row["故障描述"].startswith("MF105 EPB卡滞"):
        row["整车危害"] = "非预期的纵向移动"
        row["危害事件"] = row["危害事件"].replace(
            "EPB无法释放导致车辆无法正常起步，在坡道发生向后溜移",
            "EPB卡滞在释放状态导致无法建立驻车力，车辆在坡道发生溜移",
        )
    if row.get("结果ASIL") != "QM":
        row["安全目标"] = ""
        row["安全状态"] = ""
        row["FTTI(ms)"] = ""
    new_hara.append(row)
analysis["HARA"] = new_hara

analysis["mf_vehicle_hazards"] = [
    {
        "No.": 1,
        "Milf_ID": "EPB_Milf_001",
        "故障描述": "MF101 车辆静止且EPB处于Released状态时驾驶员拉起EPB开关后未执行拉起",
        "整车级危害": "非预期的纵向移动",
        "备注": "驾驶员请求静态拉起后驻车力未建立，坡道、蠕行或外力条件下车辆可能移动。",
    },
    {
        "No.": 2,
        "Milf_ID": "EPB_Milf_002",
        "故障描述": "MF101 整车OFF或网络休眠状态下拉起EPB开关后系统未唤醒且未执行拉起",
        "整车级危害": "非预期的纵向移动",
        "备注": "休眠状态下拉起开关未唤醒EPB，驾驶员可能误以为已驻车。",
    },
    {
        "No.": 3,
        "Milf_ID": "EPB_Milf_003",
        "故障描述": "MF102 EPB执行拉起但夹紧力不足，无法保持车辆驻车",
        "整车级危害": "非预期的纵向移动",
        "备注": "驻车制动力不足以抵抗坡度、蠕行扭矩或外力。",
    },
    {
        "No.": 4,
        "Milf_ID": "EPB_Milf_004",
        "故障描述": "MF103 EPB拉起响应延迟，车辆在驻车力建立前移动",
        "整车级危害": "非预期的纵向移动",
        "备注": "响应时间过长导致驻车力建立前车辆已经移动。",
    },
    {
        "No.": 5,
        "Milf_ID": "EPB_Milf_005",
        "故障描述": "MF104 EPB在无驾驶员拉起请求或车速超过静态门限时非预期拉起",
        "整车级危害": "非预期的减速",
        "备注": "非请求或越过静态门限施加驻车制动力，可能导致车辆突然减速。",
    },
    {
        "No.": 6,
        "Milf_ID": "EPB_Milf_006",
        "故障描述": "MF105 EPB卡滞在释放状态无法拉起",
        "整车级危害": "非预期的纵向移动",
        "备注": "EPB保持释放状态，驾驶员请求拉起后仍无法建立驻车力。",
    },
]

module_path = Path(".claude/skills/hara-analysis/scripts/claude_hara_pipeline.py")
spec = importlib.util.spec_from_file_location("pipeline", module_path)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
analysis = pipeline.postprocess_analysis(analysis, "EPB")

path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("semantic corrected EPB analysis")
