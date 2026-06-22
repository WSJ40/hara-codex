# HARA 校验与评审报告

## 摘要

- 结论：通过
- Blocking：0
- Warning：2
- derive_mf 行数：1
- mf_vehicle_hazards 行数：0
- HARA 行数：0
- sg_sum 行数：0

## Warnings

1. [sheet1-malfunction] (derive_mf[1]) 行为模型包含相反状态或方向（拉起/释放）；应确认是否存在“请求 A 却执行 B”的方向错误
2. [sheet1-style] (derive_mf[1]) sheet1 故障描述疑似混入场景/条件句；建议统一为“功能对象 + 偏离表现”的短语风格

## 需要工程师确认的假设

- 车速>3km/h时EPB拉起功能被禁止（基于'静态'名称推断）
- EPB制动力满足GB法规驻车要求
- 车速信号来自仪表，EPB系统信任该信号
- EPB开关为独立物理开关，非复用开关
- 文档中'近光灯亮灭逻辑'为错误标题，实际内容为EPB拉起逻辑
