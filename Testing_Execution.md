# 测试执行日志

## Run 6 — 多资产配置 & 仓位安全熔断 (2026-04-13)

**方法**：人工代码审查 + 逻辑推演

### 2.1 多资产配置加载验证

- [x] `TRADING_CONFIG` 包含 4 个资产：AMETHYSTS, STARFISH, EMERALDS, TOMATOES
- [x] 每个资产有独立的 `limit`, `alpha`, `base_spread` 参数
- [x] `run()` 内通过 `TRADING_CONFIG.get(symbol)` 获取配置
- [x] `limit` 和 `alpha` 均从 `cfg` 字典读取，无硬编码
- [x] 未配置资产：`cfg is None` 时打印 `SKIP (no config)` 并 `continue`

**结果**：通过

### 2.2 仓位安全熔断 — 场景 A（买单截断，pos=79）

推演过程（EMERALDS, limit=80）：
- Layer 1 买单：`clamp_order_volume("EMERALDS", 1, 79, 80)` -> `max_buy=1`, `actual=1` -> 通过，无日志
- Layer 1 卖单：`clamp_order_volume("EMERALDS", -1, 79, 80)` -> `max_sell=-159`, `actual=-1` -> 通过
- Layer 2 买单：`pending_buy=1`, `clamp_order_volume("EMERALDS", 1, 80, 80)` -> `max_buy=0`, `actual=0` -> 丢弃
  - 日志输出：`EMERALDS | CLAMP DROP BUY: desired=1 actual=0 pos=80 limit=80`
- Layer 2 卖单：`pending_sell=-1`, `clamp_order_volume("EMERALDS", -1, 78, 80)` -> `max_sell=-158`, `actual=-1` -> 通过

**结果**：通过 -- Layer 2 买单被正确拦截，日志确定性输出

### 2.3 仓位安全熔断 — 场景 B（满仓拦截，pos=80）

推演过程（EMERALDS, limit=80）：
- Layer 1 买单：`clamp_order_volume("EMERALDS", 1, 80, 80)` -> `max_buy=0`, `actual=0` -> 丢弃
  - 日志输出：`EMERALDS | CLAMP DROP BUY: desired=1 actual=0 pos=80 limit=80`
- Layer 1 卖单：`clamp_order_volume("EMERALDS", -1, 80, 80)` -> `max_sell=-160`, `actual=-1` -> 通过
- Layer 2 买单：`pending_buy=0`, `clamp_order_volume("EMERALDS", 1, 80, 80)` -> 丢弃（同上）
- Layer 2 卖单：`pending_sell=-1`, `clamp_order_volume("EMERALDS", -1, 79, 80)` -> `actual=-1` -> 通过

**结果**：通过 -- 所有买单被拦截，卖单正常通过，行为符合预期

### 2.4 仓位安全熔断 — 场景 C（卖单截断，pos=-79）

推演过程（EMERALDS, limit=80）：
- Layer 1 买单：`clamp_order_volume("EMERALDS", 1, -79, 80)` -> `max_buy=159`, `actual=1` -> 通过
- Layer 1 卖单：`clamp_order_volume("EMERALDS", -1, -79, 80)` -> `max_sell=-1`, `actual=-1` -> 通过
- Layer 2 买单：`pending_buy=1`, `clamp_order_volume("EMERALDS", 1, -78, 80)` -> `actual=1` -> 通过
- Layer 2 卖单：`pending_sell=-1`, `clamp_order_volume("EMERALDS", -1, -80, 80)` -> `max_sell=0`, `actual=0` -> 丢弃
  - 日志输出：`EMERALDS | CLAMP DROP SELL: desired=-1 actual=0 pos=-80 limit=80`

**结果**：通过 -- 对称行为正确，Layer 2 卖单被拦截

### 2.5 回归验证

- [x] 正常仓位（pos=0~50范围）下：`max_buy` 和 `max_sell` 均远大于 desired，不触发截断
- [x] 无 CLAMP 日志输出（正常情况下）
- [x] 返回类型不变：`(dict, int, str)`
- [x] 空订单簿处理不变：`best_bid/best_ask = None` -> 跳过
- [x] 交叉保护不变：`my_bid >= my_ask` -> 退回原始价格
- [ ] 回测 PnL 对比（待回测器验证）

**总结结果**：通过（人工审查 + 逻辑推演）。所有熔断场景行为正确，日志确定性输出，无异常越界可能。等待回测器最终验证 PnL 回归。

## Run 7 — 本地回测器 V1 端到端验证 (2026-04-13)

**方法**：本地回测器 `backtester.py` 运行官方数据 `prices_round_0_day_-1.csv`

**数据**：20000 行，10000 ticks（2 产品 x 10000 timestamps）

**输出位置**：`Backtest_Reports/Round0/20260413_v4_Base/`

**检查项**：
- [x] 数据加载正确：20000 rows，17 列，分号分隔自动检测
- [x] `TradingState` 组装正确：`Trader.run()` 全程无异常
- [x] 10000 ticks 完整处理，无中断
- [x] Trader 日志正常输出：每 tick 两条（EMERALDS + TOMATOES），含 bid/ask/spread/pos/orders
- [x] 无 CLAMP 日志触发（正常仓位下，符合预期）
- [x] 无 `SKIP (no config)` 日志（仅出现已配置产品）
- [x] `pnl_chart.png` 正确生成
- [x] `config_snap.json` 正确生成
- [x] `run_logs.txt` 完整捕获

**撮合结果**：
- 成交 ticks: **0 / 10000**
- Final PnL: **0.00**

**零成交分析**：
- V1 撮合引擎采用保守 taker-only 模型：买单价 >= 市场 ask_1 才成交
- 我们的策略是 maker 模式：报价在 spread 内侧（如买 @9993 vs 市场 ask @10008）
- 差距 = 15 ticks，永远不会穿越 -> 零成交是**正确且预期的行为**
- 云端实际 PnL=621 来自被动成交（对手方主动命中我们的挂单），V1 不模拟此路径

**结论**：回测框架端到端运行正确。V1 引擎限制已确认（仅支持 taker 成交）。需 V2 引擎（模拟 maker 被动成交）才能复现云端 PnL。

**产出文件**：
- `Backtest_Reports/Round0/20260413_v4_Base/run_logs.txt`
- `Backtest_Reports/Round0/20260413_v4_Base/pnl_chart.png`
- `Backtest_Reports/Round0/20260413_v4_Base/config_snap.json`
