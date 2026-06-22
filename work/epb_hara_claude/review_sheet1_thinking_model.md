# HARA 校验与评审报告

## 摘要

- 结论：通过
- Blocking：0
- Warning：4
- derive_mf 行数：1
- mf_vehicle_hazards 行数：6
- HARA 行数：33
- sg_sum 行数：6

## Warnings

1. [sheet1-malfunction] (derive_mf[1]) 功能丧失疑似按前置条件重复列出多个冗余故障；sheet1 应概括功能级偏离，前置条件放到 sheet2/HARA
2. [sheet1-malfunction] (derive_mf[1]) 行为模型提示可能存在作用量维度（制动力、夹紧力、保持力）；若该作用量在正常功能中存在，应确认是否遗漏“过大”故障
3. [sheet1-malfunction] (derive_mf[1]) 行为模型包含相反状态或方向（拉起/释放）；应确认是否存在“请求 A 却执行 B”的方向错误
4. [sheet1-malfunction] (derive_mf[1]) 功能存在相反状态或方向，非预期激活应基于行为模型确认每个非请求转换是否存在：拉起/释放

## ASIL 分布

- QM: 11
- A: 4
- B: 12
- C: 4
- D: 2

## 需要工程师确认的假设

- 车速≤3km/h判定为车辆静止
- EPB休眠指网络休眠状态下EPB处于低功耗模式
- EPB状态包括Released（释放）、Applied（拉起）、Releasing（释放中）、Applying（拉起中）
- 仪表显示提示为二级信息，非一级安全相关
- 系统仅与车速信号、网络状态、EPB开关信号交互
