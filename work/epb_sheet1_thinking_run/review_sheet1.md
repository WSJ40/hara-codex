# HARA 校验与评审报告

## 摘要

- 结论：通过
- Blocking：0
- Warning：1
- derive_mf 行数：1
- mf_vehicle_hazards 行数：0
- HARA 行数：0
- sg_sum 行数：0

## Warnings

1. [sheet1-malfunction] (derive_mf[1]) 功能存在相反状态或方向，非预期激活应基于行为模型确认每个非请求转换是否存在：拉起/释放

## 需要工程师确认的假设

- 车速≤3km/h判定为静止状态
- EPB休眠指控制单元低功耗模式，整车网络休眠指CAN总线休眠
- 释放中（Releasing）状态持续时间为从释放指令发出到卡钳完全释放的时间
- 仪表文字提示'电子驻车已启动'为EPB已拉起状态的唯一反馈方式
- EPB系统与ESP、变速箱等系统无横向控制耦合
