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

---

## Run 13 — Diagnostics-Only Batch (v5.5 baseline, 2026-04-15)

**目的**：运行已部署的诊断基础设施，产出逐日诊断摘要，不修改任何策略逻辑。

**诊断运行流程**：

```
# 前提：round1_trader.py 中 DIAG_MODE = True（仅本地诊断使用）

# 每天分别运行（每天独立 session，不共享 traderData 跨天状态）
python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_-2.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/diag_20260415/day_minus2" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/diag_20260415/raw_day_minus2.txt" 2>&1

python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_-1.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/diag_20260415/day_minus1" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/diag_20260415/raw_day_minus1.txt" 2>&1

python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_0.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/diag_20260415/day_0" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/diag_20260415/raw_day_0.txt" 2>&1

# 注意：云端提交前须将 DIAG_MODE 重置为 False
```

**输出目录**：`D:\IMC Prosperity 4\Backtest_Reports\Round1\`

**诊断指标**（每天每项均输出，见原始文件中的 `[DIAG day=...]` 段落）：

| 指标 | 来源代码 | 含义 |
|------|---------|------|
| Asset MTM PnL | backtester._print_day_diagnostics | 逐资产盯市盈亏归因 |
| P1 filled < -30 | match_orders: fill_price == best_bid | PPR Phase 1 吃单在深空仓时的成交量 |
| P2 posted < -30 | match_orders: price > best_bid, pos_at_start <= -30 | PPR Phase 2 在深空仓时的挂单意图量 |
| P2 filled < -30 | match_orders: fill_price != best_bid | PPR Phase 2 在深空仓时的实际成交量 |
| Saturation dwell | 主循环 pos 计数 | 两资产各方向饱和停留时长（ticks） |
| P1 delta histogram | DIAG_P1 print (DIAG_MODE=True) | Phase 1 卖单触发时的 bid−fv 偏差分布 |

**预期结果与决策规则**：

| 诊断结果 | 支持变更 |
|---------|---------|
| PPR ≤ −70 停留 > 5% ticks | PPR 短侧饱和已确认，进行 Change 1 或 Change 2 |
| OSM ≥ ±70 停留可与 PPR 比肩 | OSM 也是瓶颈，优先 Change 4（OSM microprice weight 降低）|
| P2 filled > P1 filled 于 pos ≤ -30 | Change 2（Phase 2 压制阈值降至 -40）为 PPR 主要修复 |
| P1 filled > P2 filled 于 pos ≤ -30 | Change 1（Phase 1 仓位门控 -40）为 PPR 主要修复 |
| Phase 1 sell delta 均 ≤ 2 | Phase 1 在深空仓时无真实 alpha，门控代价低 |

**实际诊断结果摘要（2026-04-15）**：

| Day | PPR MTM PnL | OSM MTM PnL | Total PnL | OSM >=+80 ticks | PPR <=-80 ticks |
|-----|------------|------------|-----------|----------------|----------------|
| Day -2 | +9,337 | +1,113 | +10,449 | 235 (2.35%) | 7 (0.07%) |
| Day -1 | +7,780 | +1,703 |  +9,483 |  14 (0.14%) | 0 (0.00%) |
| Day  0 | +11,099 | -2,780 |  +8,319 | 347 (3.47%) | 0 (0.00%) |
| **合计** | **+28,216** | **+36** | **+28,251** | **596 (2.0% avg)** | **7 (0.02% avg)** |

PPR Phase 1 vs Phase 2 fill ratio below pos -30: **P2 fills 3x more than P1** (consistent across all days)
Phase 1 sell delta at pos ≤ -30: **100% delta 1-2, zero delta ≥ 5** (purely marginal alpha)

**结论**：OSM 是主要瓶颈（并非 PPR）。推荐优先执行 Change 4（OSM microprice weight 0.45 → 0.25），
不在本批次实施 Change 1 或 Change 2。详见 `diag_overview.txt`。

**产出文件**：
- `Backtest_Reports/Round1/diag_overview.txt`  ← 总结报告及推荐
- `Backtest_Reports/Round1/diag_summary_day_minus2.txt`
- `Backtest_Reports/Round1/diag_summary_day_minus1.txt`
- `Backtest_Reports/Round1/diag_summary_day_0.txt`
- `Backtest_Reports/Round1/diag_20260415/raw_day_{minus2,minus1,0}.txt`  ← 完整原始输出
- `Backtest_Reports/Round1/diag_20260415/day_{minus2,minus1,0}/pnl_chart.png`

---

## Run 14 — Change 4 Validation: OSM_MICRO_WEIGHT 0.45 → 0.25 (v5.6)

**策略版本**：v5.6（相对 v5.5 仅改动 OSM_MICRO_WEIGHT 和 DIAG_MODE 复位）

**运行前提**：
- `round1_trader.py`: `OSM_MICRO_WEIGHT = 0.25`, `DIAG_MODE = False`
- `backtester.py`: 无修改（诊断基础设施保留，但 `diag_counters` 仍会计算不打印）

**本地验证运行命令**：

```
# 每天分别运行，seed=42，与 v5.5 基准完全可比
python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_-2.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.6_Change4/day_minus2" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.6_Change4/raw_day_minus2.txt" 2>&1

python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_-1.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.6_Change4/day_minus1" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.6_Change4/raw_day_minus1.txt" 2>&1

python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_0.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.6_Change4/day_0" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.6_Change4/raw_day_0.txt" 2>&1
```

**关键对比指标（v5.5 基准 vs v5.6）**：

| 指标 | v5.5 基准 | v5.6 目标方向 | 合格标准 |
|------|----------|------------|--------|
| OSM MTM PnL Day -2 | +1,113 | ≥ v5.5 | 不下降；最好上升 |
| OSM MTM PnL Day -1 | +1,703 | ≥ v5.5 | 不下降 |
| OSM MTM PnL Day  0 | −2,780 | 转正或显著减亏 | Day 0 OSM 不再是主要拖累 |
| OSM dwell ≥+80 (avg) | 2.0% (596 ticks) | 明显下降 | < 1.0%（50%削减）为理想 |
| OSM dwell ≥+70 (avg) | 5.5% (1638 ticks) | 明显下降 | < 3.0% 为理想 |
| OSM dwell ≤−80 (avg) | 0.7% (206 ticks) | 下降或持平 | 不应显著增加 |
| OSM dwell ≤−70 (avg) | 1.7% (508 ticks) | 下降或持平 | 不应显著增加 |
| PPR MTM PnL (合计) | +28,216 | 保持不变 | 偏差 < 5%（噪音范围内）|
| PPR dwell ≤−80 (avg) | 0.02% | 保持不变 | PPR 行为不受影响 |
| 总 PnL 3日合计 | +28,251 | ≥ v5.5 | 不下降为通过；上升为成功 |

**诊断输出提取方法**（运行后）：

```bash
# 提取 [DIAG day=...] 段落（含 MTM PnL 和饱和停留数据）
grep -E "^\[DIAG day=|^  (INTARIAN|ASH|Phase|→)|^    (short|long)|^\[RESULT" \
  raw_day_minus2.txt | grep -v "DIAG_P"
```

**成功判定标准**：

成功（结构性改善）：
1. OSM ≥+80 dwell 明显下降（目标 < 1%）
2. OSM MTM PnL Day 0 不再为大负数（从 −2,780 改善）
3. PPR MTM PnL 三天总计偏差 < 5%（PPR 未受影响）
4. 总系统 PnL 不低于 v5.5 基准（+28,251）

可接受（部分改善）：
1. OSM ≥+80 dwell 小幅下降（< 50%削减）但方向正确
2. OSM Day 0 仍为负但亏损显著收窄（例如 −1,000 → −500）
3. 总 PnL 未显著下降（偏差 < 10%）

失败（需回滚）：
1. OSM 饱和停留未减少或恶化
2. OSM MTM PnL 三天总计比 v5.5 更差
3. PPR MTM PnL 明显下降（> 5% 偏差）
4. 总 PnL 低于 v5.5 基准（说明减少微价格权重削弱了有效吃单信号）

**云端验证信号**（上传后观察）：

1. **OSM 仓位图形**：云端 OSM 仓位时间序列应更少出现长时间钉在 ±80 的水平段
2. **OSM PnL 贡献**：云端结果分解（若可见）中 OSM 不再是主要负贡献
3. **总云端 PnL**：与 v5.5 云端结果对比（v5.5 云端数据尚未运行，以 v5.4 2508 为参照）
4. **PPR 云端 PnL**：应与 v5.5 接近，PPR 逻辑未变

**注意**：本地 PnL 绝对值不是主要判断指标；OSM 饱和停留时间和方向性结构改善才是核心信号。

**输出目录**：`D:\IMC Prosperity 4\Backtest_Reports\Round1\v5.6_Change4\`

**实际运行结果（2026-04-15，seed=42）**：

| Day | OSM PnL | OSM>=+80 | OSM>=+70 | OSM<=-80 | OSM<=-70 | TotalPnL |
|-----|---------|---------|---------|---------|---------|---------|
| v5.5 Day -2 | +1,113 | 235 (2.35%) | 799 (8.0%) | 0 | 145 (1.5%) | +10,449 |
| v5.6 Day -2 | **-306** | 166 (1.66%) | 739 (7.4%) | 0 | 198 (2.0%) | +18,184 ★ |
| v5.5 Day -1 | +1,703 | 14 (0.14%) | 245 (2.5%) | 3 (0.03%) | 20 (0.2%) | +9,483 |
| v5.6 Day -1 | +2,605 | 19 (0.19%) | 318 (3.2%) | 39 (0.39%) | **554 (5.5%)** | +2,383 ★ |
| v5.5 Day 0 | -2,780 | 347 (3.47%) | 594 (5.9%) | 203 (2.03%) | 343 (3.4%) | +8,319 |
| v5.6 Day 0 | -2,169 | 176 (1.76%) | 371 (3.7%) | 241 (2.41%) | 423 (4.2%) | +7,788 ★ |
| **v5.5 合计** | **+36** | **596 (2.0%)** | **1638 (5.5%)** | **206 (0.7%)** | **508 (1.7%)** | **+28,251** |
| **v5.6 合计** | **+130** | **361 (1.2%)** | **1428 (4.8%)** | **280 (0.9%)** | **1175 (3.9%)** | **+28,355** ★ |
| 变化 | +94 | -235 (-39%) | -210 (-13%) | +74 (+36%) | +667 (**+131%**) | — |

★ 总 PnL 数字无效：不同OSM下单量改变了随机数消耗顺序，PPR成交决策被RNG状态污染。仅OSM指标有效。

**结论**：FAILED — 已回滚。

原因：`OSM_MICRO_WEIGHT` 是对称参数。降低权重后：
- FV对上行脉冲响应减弱 → 更多 bid 价高于 FV → Phase 1 卖单大量触发 → 短侧饱和
- Day -1 OSM ≤-70 从 20 → 554 tick（+27倍），短侧饱和问题比原始长侧更严重
- 效果：将饱和从长侧转移至短侧，净改善仅 -20%（合并长+短侧极端饱和计数）

**参数状态（回滚后）**：OSM_MICRO_WEIGHT = 0.45，DIAG_MODE = False（云端安全）

---

## Run 15 — Change 4 Rollback Confirmation (2026-04-15)

**类型**：回滚确认 / 实验关闭。无新策略逻辑。

**回滚内容**：
- `OSM_MICRO_WEIGHT`: 0.25（Change 4 测试值）→ **0.45**（v5.5 基准）
- `DIAG_MODE`: 确认为 **False**（云端安全）
- 所有其他参数在整个实验期间始终未变

**回滚原因**：

| 指标 | v5.5 基准 | v5.6 测试 | 结果 |
|------|---------|---------|------|
| OSM ≥+80 dwell (3日) | 596 tick (2.0%) | 361 tick (1.2%) | ✓ 改善 |
| OSM ≥+70 dwell (3日) | 1638 tick (5.5%) | 1428 tick (4.8%) | ✓ 轻微改善 |
| OSM ≤−80 dwell (3日) | 206 tick (0.7%) | 280 tick (0.9%) | ✗ 恶化 |
| OSM ≤−70 dwell (3日) | 508 tick (1.7%) | 1175 tick (3.9%) | ✗✗ 严重恶化 (+131%) |
| OSM Day -1 ≤−70 dwell | 20 tick | 554 tick (+27×) | ✗✗ 最差案例 |
| OSM MTM PnL (3日) | +36 | +130 | → 改善可忽略 |
| 云端 PnL | 基准参考 | 相对基准下降 | ✗ 用户确认失败 |

根因：`OSM_MICRO_WEIGHT` 是对称参数 — 降低后对上行和下行脉冲同等减感，
无法单独修复单侧饱和；0.25 将长侧饱和转移为等量短侧饱和。

**本地验证安全检查（13项参数核验）**：

```
OSM_MICRO_WEIGHT  = 0.45   ✓
DIAG_MODE         = False  ✓
OSM_EMA_ALPHA     = 0.05   ✓
OSM_ALPHA         = 0.1    ✓
OSM_LIMIT         = 80     ✓
PPR_LIMIT         = 80     ✓
SKEW_K            = 3.0    ✓
SKEW_THRESHOLD    = 0.60   ✓
ONE_SIDE_FRAC     = 0.875  ✓
MAX_MM_LOT        = 15     ✓
EMA_ALPHA         = 0.2    ✓
MICRO_WEIGHT      = 0.3    ✓
JUMP_THRESHOLD    = 15     ✓
```

**云端结果 vs 参考基准**：Change 4 云端 PnL 相对 v5.5 下降（用户确认）。
未作新云端提交；当前 round1_trader.py 已回滚至 v5.5，可直接提交。

**结论**：Change 4 实验正式关闭。当前活跃策略为 v5.5 基准（OSM_MICRO_WEIGHT=0.45）。

**Change 4 实验：CLOSED。**

**下一批次候选方向**（仅记录，不在本批次实施）：
- Path A: OSM_MICRO_WEIGHT = 0.35（温和调低，验证对称问题是否可接受）
- Path B: OSM Phase 1 双向仓位门控（`taker_buy_gate=+40`, `taker_sell_gate=−40`），
  直接限制 Phase 1 推动 OSM 仓位深度，与 FV 计算解耦，云端可移植性高

---

## Run 16 — v5.7 Path B: OSM Phase 1 双向仓位门控验证

**策略版本**：v5.7（相对 v5.5 基准新增 OSM Phase 1 taker gate）

**变更摘要**：
- `aggressive_take_and_mm()` 新增 `taker_buy_gate` / `taker_sell_gate` 参数
- OSM 调用传入 `taker_buy_gate=40, taker_sell_gate=-40`
- PPR 调用不传，默认 None，行为完全不变
- 所有 FV 公式、偏斜参数、DIAG_MODE、PPR 逻辑均未改动

**基准对比目标**：v5.5（Run 13 诊断数据）

**本地验证运行命令**（seed=42，与 v5.5 完全可比）：

```bash
python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_-2.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.7_PathB/day_minus2" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.7_PathB/raw_day_minus2.txt" 2>&1

python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_-1.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.7_PathB/day_minus1" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.7_PathB/raw_day_minus1.txt" 2>&1

python backtester.py \
  "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_0.csv" \
  -o "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.7_PathB/day_0" \
  > "d:/IMC Prosperity 4/Backtest_Reports/Round1/v5.7_PathB/raw_day_0.txt" 2>&1
```

**诊断信息提取**：

```bash
# 提取 [DIAG day=...] 段落（MTM PnL 和饱和停留数据）
grep -E "^\[DIAG day=|^  (INTARIAN|ASH|Phase|→)|^    (short|long)|^\[RESULT" \
  raw_day_minus2.txt | grep -v "DIAG_P"
```

**核心对比指标（v5.5 基准）**：

| 指标 | v5.5 基准 | v5.7 目标方向 | 合格标准 |
|------|----------|------------|--------|
| OSM dwell ≥+80 (3日) | 596 tick (2.0%) | 明显下降 | < 1.0% 为理想（50% 削减） |
| OSM dwell ≥+70 (3日) | 1638 tick (5.5%) | 明显下降 | < 3.0% 为理想 |
| OSM dwell ≤-80 (3日) | 206 tick (0.7%) | 下降或持平 | 不应显著增加 |
| OSM dwell ≤-70 (3日) | 508 tick (1.7%) | 下降或持平 | 不应显著增加（关键：Change 4 此项+131%为失败原因）|
| OSM MTM PnL (3日合计) | +36 | ≥ v5.5 | 不下降 |
| OSM MTM PnL Day 0 | -2,780 | 减亏或转正 | Day 0 OSM 不再是主要拖累 |
| PPR MTM PnL (3日合计) | +28,216 | 保持不变 | 偏差 < 5%（PPR 逻辑未动）|
| 总 PnL 3日合计 | +28,251 | ≥ v5.5 | 不下降为通过；上升为成功 |

**前半段 PnL 行为专项检查**（核心假设：OSM 库存损坏是前半段扁平的原因）：

运行后从 `pnl_chart.png` 或原始 log 检查：
1. 前 50% ticks（0-5000）的 PnL 累计值 vs 后 50% ticks（5001-10000）
2. OSM 在前 2000 ticks 内首次触达 ≥+70 的时间 — 门控后应明显推迟
3. 前半段 OSM 仓位是否在 ±40 附近震荡而非直接推至 ±80
4. 总 PnL 曲线在前半段是否出现更早的正斜率段（而非长时间水平）

**回滚条件**（满足任意一项则回滚至 v5.5）：
- OSM 饱和停留（≥+80 或 ≤-80）未减少或恶化
- OSM ≤-70 dwell 显著增加（重演 Change 4 短侧饱和问题）
- OSM MTM PnL 三天合计比 v5.5 更差
- 总系统 PnL 明显下降（> 10% 偏差）
- PPR MTM PnL 出现显著偏差（> 5%）
- 前半段 PnL 行为完全无改善，OSM 仓位行为与 v5.5 相似

**云端验证清单**（本地通过后提交）：

1. 上传 `round1_trader.py`（v5.7，DIAG_MODE=False 确认）
2. 对比云端 v5.5 基准（最新已上传的有效基准版本）
3. 检查云端 OSM 仓位时间序列：是否减少了长时间钉在 ±80 的水平段
4. 检查云端总 PnL：是否高于 v5.5 云端结果
5. 特别检查前半段云端 PnL 路径：是否出现比 v5.5 更早、更连续的增长段
6. 若云端 OSM 仓位在 ±40 附近出现更多往返震荡（而非直冲 ±80），视为正面信号
7. PPR 云端 PnL 应与 v5.5 接近；若 PPR 出现大幅偏差，调查 RNG 污染问题

**改进 vs 失败的判断**：
- 改进：OSM 极端区停留时间减少，总 PnL 不下降，前半段曲线更陡
- 失败：OSM 短侧新增饱和，或 PnL 明显下滑，或行为与 v5.5 无区别

**输出目录**：`D:\IMC Prosperity 4\Backtest_Reports\Round1\v5.7_PathB\`

---

## Run 17 — v5.8 完整回滚至 v5.4 参数基线 (2026-04-15)

**回滚原因**：
- v5.6 云端 PnL ≈ 2205（低于 v5.4 的 2441）
- v5.7 云端 PnL = 2205（与 v5.6 相同，同样低于 2441）
- v5.6 和 v5.7 均在 v5.5 参数基础上改动，无法突破 v5.5 造成的性能上限
- 根因：v5.5 的三个参数变更（OSM_MICRO_WEIGHT 0.20→0.45, SKEW_K 2.0→3.0, SKEW_THRESHOLD 0.75→0.60）是云端下跌的来源

**回滚内容**：
- `OSM_MICRO_WEIGHT`: 0.45 → **0.20**
- `SKEW_K`: 3.0 → **2.0**
- `SKEW_THRESHOLD`: 0.60 → **0.75**
- Phase 1 gate (v5.7) 完全移除

**本地验证结果（seed=42）**：

| Day | 结果 | v5.4 基准 | 吻合 |
|-----|------|---------|------|
| Day -2 | +13,022 | +13,022 | ✓ 逐位吻合 |
| Day -1 | +13,636 | +13,636 | ✓ 逐位吻合 |
| Day  0 | +13,554 | +13,554 | ✓ 逐位吻合 |
| **合计** | **+40,212** | **+40,212** | ✓ |

末仓亦完全吻合（OSM: +47/+27/-42；PPR: +75/-71/-33）。

**云端目标**：恢复至 2441 水平。提交 v5.8 后对比 v5.4 云端结果。

**输出目录**：`D:\IMC Prosperity 4\Backtest_Reports\Round1\v5.8_Rollback\`
