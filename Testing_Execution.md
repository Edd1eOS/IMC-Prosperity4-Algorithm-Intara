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

---

## Run 8 — Round 1 首次回测：产品名错误导致零成交 (2026-04-14)

**方法**：本地回测器 `backtester.py` 运行 Round 1 官方数据 `prices_round_1_day_0.csv`（v5.0 初始版本，产品名仍为 EMERALDS/TOMATOES）

**数据**：20000 行，10000 ticks（2 产品 × 10000 timestamps）

**检查项**：
- [x] 数据加载正确：20000 rows，17 列，分号分隔
- [x] `backtester.py` import 已修正为 `from round1_trader import ...`
- [x] Trader.run() 无异常（未报错，但无日志输出）
- [x] 10000 ticks 处理完成，无中断

**撮合结果**：
- 成交 ticks: **0 / 10000**
- Final PnL: **0.00**

**零成交根因分析**：
- Round 1 实际产品为 `ASH_COATED_OSMIUM` 和 `INTARIAN_PEPPER_ROOT`
- 代码中 `if "EMERALDS" in state.order_depths` 永远为 False → result dict 为空 → 无订单提交
- 已通过 `head -5` 查看 CSV 确认产品名不匹配

**结论**：需重命名产品名并分析 Round 1 资产特征。

---

## Run 9 — Round 1 产品名修复 + 架构重构：MM 仓位爆炸 Bug (2026-04-14)

**方法**：修复产品名 + 完整 v5 策略重写后首次回测（无盘口非穿越钳制，无 MAX_MM_LOT 限制）

**数据**：`prices_round_1_day_0.csv`，10000 ticks

**产品特征分析（基于三天数据，非零 mid_price）**：

| 产品 | Day -2 | Day -1 | Day 0 | 结论 |
|------|--------|--------|-------|------|
| ASH_COATED_OSMIUM | mean=9998，std=5.2 | mean=10001，std=4.5 | mean=10002，std=5.7 | 固定FV=10000 |
| INTARIAN_PEPPER_ROOT | mean=10500，开盘≈10000，收盘≈11000 | mean=11500，+1000 | mean=12500，+1000 | 每天线性趋势+1000 |

**撮合结果**：
- 成交 ticks: 8827 / 10000
- Final PnL: **-11,840,252.00**

**负收益根因分析**：
- pos=±80 时，MM 卖单经库存偏斜后价格 = `fv + 1 - skew = 10001 - 8 = 9993`，恰好 `≤ best_bid=9993`
- V3 引擎判定为 Taker（price ≤ best_bid → 100% fill）→ 瞬间从 +80 打到 -80
- 反向同理：pos=-80 时 MM 买单变 Taker → 瞬间从 -80 打到 +80
- 每次来回（160 手 × spread ≈ 15）= 亏损 2400，约 4400 次循环 → 亏损约 10M

**结论**：MM 报价必须钳制在盘口内侧，禁止穿越。

---

## Run 10 — 盘口非穿越钳制修复（MM 仍有 160 手大单问题）(2026-04-14)

**方法**：加入 `mm_bid = min(mm_bid, best_ask - 1)` 和 `mm_ask = max(mm_ask, best_bid + 1)` 钳制后回测

**数据**：`prices_round_1_day_0.csv`，10000 ticks

**撮合结果**：
- 成交 ticks: 5225 / 10000
- Final PnL: **-4,702,558.00**

**分析**：
- Taker 填单消除：仓位不再每 tick 完全翻转
- 但 pos=±80 时 buy_cap/sell_cap 仍为 160 手，单笔 MM 挂单 160 手
- 一旦 30% 概率触发，依然从极端到极端（160 手 × skewed price 差 ≈ 11 → 亏 1760/循环）
- PnL 改善：-11.8M → -4.7M，但仍为负

**结论**：需引入单笔 MM 挂单量上限（MAX_MM_LOT）。

---

## Run 11 — MAX_MM_LOT=15 三天全量验证（首次转正）(2026-04-14)

**方法**：加入 `MAX_MM_LOT = 15`，`buy_cap = min(limit - sim_pos, 15)` 后对三天数据全量回测

**数据**：`prices_round_1_day_{-2,-1,0}.csv`，每天 10000 ticks

**输出位置**：`Backtest_Reports/Round1/20260414_v5_AggressiveTaker/`

**检查项**：
- [x] 产品名正确：`ASH_COATED_OSMIUM` 和 `INTARIAN_PEPPER_ROOT` 均出现在日志
- [x] 每 tick 两条日志（`OSM |` 和 `PPR |`），无异常
- [x] 前 3 tick 显示 PPR warmup，第 4 tick 起出现完整 ema/micro/fv 字段
- [x] 无 Python 异常或 traceback
- [x] 仓位变化平滑（无 160 手单次翻转），最大单次成交 ≤ MAX_MM_LOT=15（MM 部分）
- [x] `pnl_chart.png` 和 `config_snap.json` 正确生成

**撮合结果（V3 随机撮合引擎，random.seed=42）**：

| Day | 数据文件 | 成交 ticks | Final PnL | ASH_COATED_OSMIUM | INTARIAN_PEPPER_ROOT |
|-----|---------|-----------|-----------|-------------------|----------------------|
| Day -2 | prices_round_1_day_-2.csv | 7127 / 10000 | **+66,013.50** | pos=+61, cash=-586,101 | pos=-80, cash=+922,631 |
| Day -1 | prices_round_1_day_-1.csv | 7180 / 10000 | **+77,964.00** | pos=-22, cash=+259,880 | pos=-54, cash=+686,020 |
| Day  0 | prices_round_1_day_0.csv  | 7218 / 10000 | **+60,143.00** | pos=-65, cash=+672,635 | pos=+60, cash=-742,037 |
| **合计** | — | — | **+204,120.50** | — | — |

**结论**：三天全部正收益，V5 策略验证通过。关键修复为：① 盘口非穿越钳制消除 MM Taker 填单；② MAX_MM_LOT=15 防止单次 160 手仓位爆炸。

**产出文件**：
- `Backtest_Reports/Round1/20260414_v5_AggressiveTaker/pnl_chart.png`
- `Backtest_Reports/Round1/20260414_v5_AggressiveTaker/config_snap.json`

---

## Run 12 — v5.4 三天全量验证：回测器校准 + 动态OSM FV + 非线性偏斜 (2026-04-14)

**方法**：本地回测器 `backtester.py`（v5.4 校准版）运行 Round 1 三天官方数据

**关键变更（相比 Run 11）**：
- `FILL_PROB_IMPROVEMENT`: 0.3 → 0.03；`FILL_PROB_QUEUE`: 0.1 → 0.02
- MTM 前向填充：`last_valid_mid` 防止 `pos × 0` 估值尖刺
- OSM FV：硬编码 10000 → 慢EMA(alpha=0.05)×0.8 + microprice×0.2；冷启动守 10000
- 库存偏斜：线性 → 指数型 `compute_skew()`；pos≥70 时单边压制（仅 Maker 层）
- 移除 Module 2/3 print

**数据**：`prices_round_1_day_{-2,-1,0}.csv`，每天 10000 ticks

**输出位置**：`Backtest_Reports/Round1/20260414_v5.4_DynamicFV/day_{-2,-1,0}/`

**检查项**：
- [x] 三天均无 Python 异常
- [x] `pnl_chart.png` 和 `config_snap.json` 正确生成（各天子目录）
- [x] OSM 末仓不再钉在 ±80：Day-2=+47，Day-1=+27，Day0=-42（库存回归有效）
- [x] 无 print 日志洪流（Module 2/3 常规 print 已移除）
- [x] OSM ERROR / PPR ERROR 均未出现

**撮合结果（V3 随机撮合引擎，random.seed=42，FILL_PROB=0.03/0.02）**：

| Day | 数据文件 | 成交 ticks | Final PnL | ASH_COATED_OSMIUM | INTARIAN_PEPPER_ROOT |
|-----|---------|-----------|-----------|-------------------|----------------------|
| Day -2 | prices_round_1_day_-2.csv | 1419 / 10000 | **+13,022.00** | pos=+47, cash=-467,469 | pos=+75, cash=-814,316 |
| Day -1 | prices_round_1_day_-1.csv | 1437 / 10000 | **+13,636.00** | pos=+27, cash=-265,528 | pos=-71, cash=+860,968 |
| Day  0 | prices_round_1_day_0.csv  | 1428 / 10000 | **+13,554.00** | pos=-42, cash=+420,642 | pos=-33, cash=+442,206 |
| **合计** | — | — | **+40,212.00** | — | — |

**与 v5 对比分析**：

| 指标 | v5 (Run 11) | v5.4 (Run 12) | 说明 |
|------|------------|--------------|------|
| Fill prob | 0.3 / 0.1 | 0.03 / 0.02 | 10x 降低 |
| 成交 ticks/天 | ~7100 | ~1430 | 5x 减少，符合预期 |
| PnL/天 | ~67k | ~13.4k | ~5x 降低，与云端差距缩小 |
| OSM 末仓范围 | -65 ~ +61（偏极端） | -42 ~ +47（回归中心） | 动态FV+指数偏斜效果 |
| 本地/云端比 | ~26x (66k/2.5k) | ~5x (13k/2.5k) | 回测器失真大幅修复 |

**结论**：
1. 回测器校准成功，本地 PnL 从 26x 压缩至 5x 云端比，估值尖刺消除
2. OSM 动态 FV 有效：末仓中心化，不再长期套牢于极端仓位
3. 剩余 5x 本地/云端差距来自云端对手盘逆向选择、撮合延迟等不可模拟因素
4. 下一步优化方向：PPR 趋势偏多（当前策略中性，未利用 +1000/天确定性趋势）

**产出文件**：
- `Backtest_Reports/Round1/20260414_v5.4_DynamicFV/day_-2/pnl_chart.png`
- `Backtest_Reports/Round1/20260414_v5.4_DynamicFV/day_-1/pnl_chart.png`
- `Backtest_Reports/Round1/20260414_v5.4_DynamicFV/day_0/pnl_chart.png`
- `Backtest_Reports/Round1/20260414_v5.4_DynamicFV/day_{-2,-1,0}/config_snap.json`
