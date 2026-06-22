# HARA 校验与评审报告

## 摘要

- 结论：通过
- Blocking：0
- Warning：0
- derive_mf 行数：1
- mf_vehicle_hazards 行数：0
- HARA 行数：0
- sg_sum 行数：0

## 需要工程师确认的假设

- AUTO档自动灯光逻辑由其他模块提供，本文档未详细定义
- 组合开关CAN报文0x133为外部输入
- 车速信号CAN报文0x121来自ESP
- 光照强度CAN报文来自光照传感器
- 近光灯驱动电路故障诊断能力假设存在
