# HARA 校验与评审报告

## 摘要

- 结论：通过
- Blocking：0
- Warning：4
- derive_mf 行数：1
- mf_vehicle_hazards 行数：11
- HARA 行数：52
- sg_sum 行数：11

## Warnings

1. [sheet1-malfunction] (derive_mf[1]) 非预期激活描述偏泛；对于相反状态（左/右）建议说明非预期发生的是哪一方向
2. [scenario] (HARA[11]) E0 表示场景不可信，不应同时保留碰撞/受伤类危险事件；应改为可信低风险场景或删除危险后果
3. [sec-scene-alignment] (HARA[15]) SEC 理由引用高速条件，但场景道路/车速未体现高速
4. [sec-scene-alignment] (HARA[24]) SEC 理由引用高速条件，但场景道路/车速未体现高速

## ASIL 分布

- QM: 24
- A: 10
- B: 9
- C: 8
- D: 1

## 需要工程师确认的假设

- 系统仅控制前转向信号灯，后转向信号灯由其他控制器负责
- 正常闪烁频率与故障快闪频率的具体数值未在文档中定义
- 掉线保持10s后转向灯熄灭，不恢复到默认关闭状态需进一步确认
- 0x38A报文仅包含左/右转向灯状态，不包含 Hazard 报警（双闪）状态
