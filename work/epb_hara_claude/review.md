# HARA 校验与评审报告

## 摘要

- 结论：通过
- Blocking：0
- Warning：0
- derive_mf 行数：1
- mf_vehicle_hazards 行数：6
- HARA 行数：33
- sg_sum 行数：6

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
