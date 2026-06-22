# HARA 校验与评审报告

## 摘要

- 结论：通过
- Blocking：0
- Warning：5
- derive_mf 行数：1
- mf_vehicle_hazards 行数：4
- HARA 行数：19
- sg_sum 行数：7

## Warnings

1. [sheet1-malfunction] (derive_mf[1]) 近光灯应确认是否存在亮度过大故障
2. [sheet1-malfunction] (derive_mf[1]) 近光灯应确认是否存在亮度过小故障
3. [sheet1-malfunction] (derive_mf[1]) 近光灯非预期激活建议明确非预期打开和/或非预期关闭
4. [sheet1-malfunction] (derive_mf[1]) 近光灯应确认请求打开却关闭、请求关闭却打开的方向错误
5. [sheet1-malfunction] (derive_mf[1]) 卡滞故障应写明卡滞在具体状态

## ASIL 分布

- QM: 2
- A: 4
- B: 4
- C: 6
- D: 3

## 需要工程师确认的假设

- 车辆前向视野主要依赖近光灯照明
- 夜间指环境光照不足、驾驶员依赖近光灯观察道路的状况
- 语音提示故障不影响近光灯本体功能
- 美版指示灯故障不影响近光灯本体功能
- 组合开关硬线信号作为CAN掉线时的备份信号来源
- AUTO档逻辑由自动灯光功能决定，本分析聚焦近光灯本体
