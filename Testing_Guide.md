# 测试指南

## 1. 基础烟雾测试（每次改动后必做）

在命令行运行回测：

```sh
prosperity4btx tut_round_trader.py 0
```

**通过标准**：
- 无异常或 traceback
- 显示 PnL 输出
- 沙盒日志中无 "exceeded limit" 警告

**返回值检查**：
- `run()` 返回类型为 `(dict[Symbol, list[Order]], int, str)`
- 空订单簿不崩溃（一侧无报价时正确跳过）
- 仅从 `datamodel` 导入（平台提供）

---

## 2. 多资产配置加载验证

**目标**：确认 `TRADING_CONFIG` 字典被正确读取，每个资产使用独立参数。

**方法**：
1. 检查代码顶部 `TRADING_CONFIG` 是否包含所有目标资产（EMERALDS, TOMATOES, AMETHYSTS, STARFISH）
2. 确认 `run()` 方法内通过 `TRADING_CONFIG.get(symbol)` 获取配置
3. 确认 `limit` 和 `alpha` 均从 `cfg` 字典读取，而非硬编码常量
4. 验证未配置资产的处理：若 `cfg is None`，应打印 `SKIP (no config)` 并跳过

**预期日志**（针对未配置资产）：
```
UNKNOWN_ASSET | SKIP (no config) | pos=0
```

---

## 3. 仓位安全熔断机制验证

**目标**：确认 `clamp_order_volume()` 在极端仓位下正确截断订单量。

### 场景 A：买单截断

**构造条件**：`position = 79`，`limit = 80`，算法尝试买入 1 手（Layer 1）

**预期行为**：
- Layer 1 买单：`desired=1`，`max_buy = 80 - 79 = 1`，`actual=1` -> 正常通过，无 CLAMP 日志
- Layer 2 买单：`desired=1`，但此时 `pending_buy=1`，虚拟仓位 = `79 + 1 = 80`，`max_buy = 80 - 80 = 0`，`actual=0` -> 丢弃
- 预期日志：`EMERALDS | CLAMP DROP BUY: desired=1 actual=0 pos=80 limit=80`

### 场景 B：满仓完全拦截

**构造条件**：`position = 80`，`limit = 80`，算法尝试买入 1 手

**预期行为**：
- `max_buy = 80 - 80 = 0`，`actual=0` -> 买单完全丢弃
- 卖单正常通过（仍有卖出空间）
- 预期日志：`EMERALDS | CLAMP DROP BUY: desired=1 actual=0 pos=80 limit=80`

### 场景 C：卖单截断（对称验证）

**构造条件**：`position = -79`，`limit = 80`，算法尝试卖出 1 手

**预期行为**：
- Layer 1 卖单：`desired=-1`，`max_sell = -80 - (-79) = -1`，`actual=-1` -> 正常通过
- Layer 2 卖单：虚拟仓位 = `-79 + (-1) = -80`，`max_sell = -80 - (-80) = 0`，`actual=0` -> 丢弃
- 预期日志：`EMERALDS | CLAMP DROP SELL: desired=-1 actual=0 pos=-80 limit=80`

---

## 4. 回归验证

**目标**：确认正常仓位下（如 `position=0` 或 `position=30`）行为与重构前完全一致。

**方法**：运行回测，对比 PnL 输出是否与之前版本（v3, PNL=621）一致。

**通过标准**：
- 日志中无 CLAMP 相关输出（正常仓位下永远不触发截断）
- PnL 不变或在误差范围内