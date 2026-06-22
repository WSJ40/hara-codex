# HARA 校验与评审报告

## 摘要

- 结论：通过
- Blocking：0
- Warning：5
- derive_mf 行数：1
- mf_vehicle_hazards 行数：6
- HARA 行数：33
- sg_sum 行数：6

## Warnings

1. [sheet1-malfunction] (derive_mf[1]) 功能丧失疑似按前置条件重复列出多个冗余故障；sheet1 应概括功能级偏离，前置条件放到 sheet2/HARA
2. [sheet1-malfunction] (derive_mf[1]) 存在作用量/强度维度，建议确认是否遗漏“过大”故障
3. [sheet1-malfunction] (derive_mf[1]) EPB 拉起应确认是否存在夹紧力过大故障
4. [sheet1-malfunction] (derive_mf[1]) EPB 功能丧失描述偏具体，建议概括为“驻车时 EPB 无法拉起”等功能级故障
5. [sheet1-malfunction] (derive_mf[1]) EPB 拉起应确认请求拉起却执行释放的方向错误

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
