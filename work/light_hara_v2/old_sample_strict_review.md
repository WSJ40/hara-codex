# HARA 校验与评审报告

## 摘要

- 结论：不通过
- Blocking：14
- Warning：0
- derive_mf 行数：3
- mf_vehicle_hazards 行数：10
- HARA 行数：10
- sg_sum 行数：3

## Blocking Findings

1. [source-functions] (derive_mf) sheet1 子功能不在源文档功能清单中：近光灯亮灭控制
2. [source-functions] (derive_mf) sheet1 子功能不在源文档功能清单中：夜间行车开灯语音提示
3. [source-functions] (derive_mf) sheet1 子功能不在源文档功能清单中：近光灯故障状态上报
4. [source-functions] (derive_mf) 源文档功能清单中的功能未进入 sheet1：近光灯
5. [scenario-coverage] (mf_vehicle_hazards[1]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF101 低照度或夜间场景下近光灯无法按驾驶员请求或AUTO逻辑点亮 / 驾驶员视野丢失或者降低
6. [scenario-coverage] (mf_vehicle_hazards[2]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF102 近光灯在驾驶员请求或AUTO逻辑满足后点亮过晚 / 驾驶员视野丢失或者降低
7. [scenario-coverage] (mf_vehicle_hazards[3]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF103 近光灯未请求时非预期点亮 / 其他驾驶员/行人误判
8. [scenario-coverage] (mf_vehicle_hazards[4]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF103 近光灯应保持点亮时非预期熄灭 / 驾驶员视野丢失或者降低
9. [scenario-coverage] (mf_vehicle_hazards[5]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF104 近光灯状态卡滞在熄灭状态 / 驾驶员视野丢失或者降低
10. [scenario-coverage] (mf_vehicle_hazards[6]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF104 近光灯状态卡滞在点亮状态 / 其他驾驶员/行人误判
11. [scenario-coverage] (mf_vehicle_hazards[7]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF201 夜间行驶且灯光开关处于OFF或小灯档时未发出开灯语音提示 / 失去报警
12. [scenario-coverage] (mf_vehicle_hazards[8]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF202 夜间行车开灯语音提示发出过晚 / 失去报警
13. [scenario-coverage] (mf_vehicle_hazards[9]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF301 近光灯实际故障时未上报故障状态 / 失去报警
14. [scenario-coverage] (mf_vehicle_hazards[10]) 非无危害故障至少需要 3 条有效 HARA 场景，当前 1 条：MF302 近光灯无故障时非预期上报故障状态 / 驾驶员获取错误的信息

## ASIL 分布

- QM: 6
- A: 2
- B: 1
- C: 1
- D: 0

## 需要工程师确认的假设

- 需求文档未给出车型、市场和灯具照射性能，按普通乘用车合理预期使用进行 HARA。
- 近光灯故障状态和夜间开灯语音提示属于辅助 HMI/告警功能，其危害成立需要驾驶员依赖该提示并且处于低照度行驶场景。
- FTTI 为 HARA 初稿工程估计值，用于后续功能安全概念评审确认。
