# HARA 校验与评审报告

## 摘要

- 结论：不通过
- Blocking：6
- Warning：0
- derive_mf 行数：1
- mf_vehicle_hazards 行数：6
- HARA 行数：6
- sg_sum 行数：3

## Blocking Findings

1. [scenario-coverage] (mf_vehicle_hazards[1]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF101 车辆静止且驾驶员拉起EPB开关后EPB未执行拉起 / 非预期的纵向移动
2. [scenario-coverage] (mf_vehicle_hazards[2]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF102 EPB执行拉起但夹紧力不足，无法保持车辆驻车 / 非预期的纵向移动
3. [scenario-coverage] (mf_vehicle_hazards[3]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF103 EPB在驾驶员拉起开关后响应过晚，车辆在驻车力建立前移动 / 非预期的纵向移动
4. [scenario-coverage] (mf_vehicle_hazards[4]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF104 EPB在无驾驶员拉起请求或车速超过静态门限时非预期拉起 / 非预期的减速
5. [scenario-coverage] (mf_vehicle_hazards[5]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF105 EPB卡滞在释放状态 / 非预期的纵向移动
6. [scenario-coverage] (mf_vehicle_hazards[6]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF105 EPB卡滞在拉起状态 / 无法纵向移动

## ASIL 分布

- QM: 3
- A: 1
- B: 2
- C: 0
- D: 0

## 需要工程师确认的假设

- 需求文档未提供车辆质量、坡度范围、执行器夹紧力、HMI详细提示和市场使用分布，按普通乘用车合理预期使用分析。
- 静态开关拉起的正常操作域为静止或车速不大于3km/h；非预期激活可作为越域故障分析，但必须明确其越过车速门限或请求条件。
- FTTI 为 HARA 初稿工程估计值，后续需结合EPB执行器响应、坡道保持能力和车辆架构确认。
