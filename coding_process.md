# Coding Process

## Entry 1 — Minimal Runnable Skeleton

**Date**: 2026-04-09

**What changed**:
- Rewrote `tut_round_trader.py` from scratch
- Old code had `Trader.__init__(self, name)` (wrong signature) and no `run()` method
- New code: platform-compliant `Trader` class with `run(self, state: TradingState)` returning `(orders, conversions, traderData)`
- Trivial strategy: buy 1 lot at best ask, sell 1 lot at best bid, per product per tick
- Position limit awareness: skip order if would exceed +/-80

**Why**:
- Previous code did not match the IMC Prosperity 4 platform contract at all
- Goal is structural correctness — run through the trading pipeline without errors

**Result**:
- File is structurally correct per platform contract
- Only local "error" is unresolved `datamodel` import (expected — provided by platform)
- Awaiting backtester verification

**Effective**: Yes — skeleton matches platform contract exactly

## Entry 2 — Basic Market Making

**Date**: 2026-04-09

**What changed**:
- Replaced market-taking logic with market-making logic in `tut_round_trader.py`
- Phase 1 bought at best_ask and sold at best_bid (crossed spread, paid spread every tick)
- Phase 2 posts buy at best_bid and sell at best_ask (provides liquidity, earns spread when filled)
- Added structured `print()` log line per product per tick: symbol, bid, ask, spread, position, order count
- Extracted `best_bid` / `best_ask` into named variables for clarity

**Why**:
- Market taking guarantees loss equal to spread per tick
- Market making inverts this: if both sides fill, we earn the spread
- Logging needed for observability without external tooling

**Result**:
- Code compiles (only expected `datamodel` import warning)
- Orders now post on same side as book (bid side buy, ask side sell)
- Log output captured by backtester stdout
- Awaiting backtester run for PnL verification

**Effective**: Pending backtester verification

## Entry 3 — Competitive Market Making (Phase 2.5)

**Date**: 2026-04-09

**What changed**:
- Upgraded pricing from passive quoting (at best_bid/best_ask) to inside-spread quoting
- When spread > 1: buy at best_bid + 1, sell at best_ask - 1
- When spread <= 1: fallback to best_bid / best_ask (no room to improve)
- Added crossing guard: if my_bid >= my_ask after adjustment, revert to original prices
- Updated log line to include my_bid / my_ask (chosen prices vs. market prices)

**Why**:
- Passive quoting at best_bid/best_ask queues behind existing orders, low fill probability
- Posting inside the spread (price improvement) jumps to front of queue
- Trade-off: slightly less profit per fill, but dramatically higher fill rate

**Hypothesis**:
- Fill rate will increase significantly
- PnL curve should become non-flat (dynamic fluctuation instead of straight line)

**Risk**:
- Reduced per-trade profit (tighter spread captured)
- If spread is always 1, no improvement over Phase 2

**Result**:
- Code compiles (only expected `datamodel` import warning)
- Crossing guard verified: my_bid < my_ask always holds
- Awaiting backtester run for PnL verification

**Effective**: Pending backtester verification

## Entry 4 — Multi-asset Config & Hard Limits

**Date**: 2026-04-13

**What changed**:
- Replaced `POSITION_LIMITS` dict + `ALPHA` scalar with unified `TRADING_CONFIG` composite dictionary
- Each asset now has independent `limit`, `alpha`, `base_spread` parameters
- Added `clamp_order_volume()` function: hard-clamps order volume before Order creation
  - Buy: `actual = min(desired, limit - position)`, drop if <= 0
  - Sell: `actual = max(desired, -limit - position)`, drop if >= 0
  - Deterministic log output on every clamp/drop event
- Layer 2 orders now account for pending Layer 1 volume when computing remaining capacity
- Config lookup: `TRADING_CONFIG.get(symbol)` with explicit skip + log if asset has no config entry
- Pre-reserved config slots for R1 assets: AMETHYSTS (limit=20), STARFISH (limit=20)

**Why**:
- Round 1 introduces multiple assets with different position limits and volatility profiles
- Single `ALPHA` and flat `POSITION_LIMITS` dict cannot express per-asset parameters
- Old position check (`position + N <= limit`) was correct but implicit and fragile — no log, no clamp, relied on hardcoded layer counts
- Platform rejects orders exceeding position limits silently; hard clamp prevents wasted order slots

**Hypothesis**:
- No behavioral change for EMERALDS/TOMATOES in tutorial round (same limit=80, alpha=0.1)
- Framework ready for R1 multi-asset deployment with zero structural changes
- CLAMP logs will fire when position approaches limit, providing observability for debugging

**Result**:
- Code compiles (only expected `datamodel` import warning)
- Awaiting backtester verification

## Entry 5 — Round 1 Complete Strategy Rewrite (v5)

**Date**: 2026-04-14

**What changed**:
- Renamed strategy file from `tut_round_trader.py` to `round1_trader.py`; updated `backtester.py` import accordingly
- Identified actual Round 1 products by analyzing official CSV data:
  - `ASH_COATED_OSMIUM`: std≈5, mean≈10000 across all 3 days → fixed FV asset (replaces EMERALDS role)
  - `INTARIAN_PEPPER_ROOT`: trends +1000/day (10000→11000→12000→13000), std≈288 → trend asset (replaces TOMATOES role)
- Introduced four major architectural changes:

  **1. State Persistence**: `traderData` JSON stores `ppr_history` (up to 20 micro-prices for PEPPER_ROOT EMA). Wrapped in `try/except` — parse failures initialize empty dict silently.

  **2. Aggressive Taker Logic**: New `aggressive_take_and_mm()` helper. Phase 1 sweeps all asks strictly below FV (buy) and all bids strictly above FV (sell) at 100% V3 fill probability. Uses `sim_pos` to track cumulative intent and never exceed `±limit`.

  **3. Dynamic Fair Value for PEPPER_ROOT**: `compute_microprice()` computes volume-weighted mid (bid*q_ask + ask*q_bid) / (q_bid+q_ask). EMA(alpha=0.2) over rolling 20 micro-prices. Final FV = 70% EMA + 30% micro-price for trend stability with current-book correction.

  **4. Inventory-Skewed MM with Two Critical Guards**:
     - *Quote non-crossing clamp*: `mm_bid = min(mm_bid, best_ask - 1)`, `mm_ask = max(mm_ask, best_bid + 1)` — prevents V3 engine from classifying passive MM orders as Taker (100% fill)
     - *MAX_MM_LOT = 15*: caps single MM order at 15 lots — prevents a single 30%-probability fill from swinging position 160 lots from one extreme to the other

- Replaced flat `TRADING_CONFIG` with OSM/PPR-specific constants; removed unused `clamp_order_volume()` helper
- Replaced verbose per-tick book print with compact `OSM | pos= | fv=` and `PPR | pos= | ema= | micro= | fv=` log lines

**Why**:
- Round 1 launched; actual products differ completely from tutorial round names
- Old strategy had no aggressive taker → missed all 100% Taker fill opportunities
- Old fixed 1-lot sizing → near-zero capital utilization under limit=80
- No `traderData` state → PEPPER_ROOT EMA impossible; every tick was stateless
- Without MAX_MM_LOT cap: at pos=±80, remaining capacity is 160; a single 30%-probability fill causes 160-lot swing across the full range → systematic round-trip losses at every spread crossing

**Debug History**:
- v5.0 (product names only): 0 fills — `EMERALDS`/`TOMATOES` not in Round1 book
- v5.1 (renamed products, no guards): PnL = -11,840,252; 160-lot oscillations at ±80 every ~2 ticks
- v5.2 (+ non-crossing clamp): PnL = -4,702,558; taker fills eliminated but lot-size bombs remained
- v5.3 (+ MAX_MM_LOT=15): PnL positive, all 3 days verified

**Result** (V3 stochastic engine, random.seed(42)):
- Day -2: 7127 ticks with fills, PnL = **+66,013.50**
- Day -1: 7180 ticks with fills, PnL = **+77,964.00**
- Day  0: 7218 ticks with fills, PnL = **+60,143.00**
- 3-day total: **+204,120.50**

**Effective**: Yes — first strategy to produce positive PnL on Round 1 data

## Entry 6 — v5.4: Backtester Calibration + Dynamic OSM FV + Non-linear Skew

**Date**: 2026-04-14

**What changed**:

### backtester.py
- `FILL_PROB_IMPROVEMENT`: 0.3 → **0.03**；`FILL_PROB_QUEUE`: 0.1 → **0.02**
  - 目的：将本地 PnL 绝对值从 ~6万/天 压制至 ~1.3万/天，与云端实盘（2508）对齐量级
- **MTM 前向填充（Forward-fill）**：新增 `last_valid_mid` 字典，在每个 tick 更新有效 mid_price；构建 `filled_mid_prices` 时采用显式循环——优先取当前有效值，缺失则回落至历史最后有效值，防止 `pos × 0` 导致 MTM 估值骤降/骤升

### round1_trader.py
- `import math` 加入（用于 `math.exp()`）
- **OSM 动态 FV**（替换硬编码 10000）：
  - 新增 `OSM_EMA_ALPHA=0.05`（慢 EMA，约19期）、`OSM_MICRO_WEIGHT=0.2`、`OSM_MIN_HISTORY=3`
  - 新增 `osm_history` 列表存入 `traderData` JSON，跨 tick 持久化
  - FV = `0.8 × slow_EMA + 0.2 × microprice`；冷启动或盘口真空时坚守 `OSM_FV=10000`（Patch 2：防冷启动震荡）
- **非线性指数库存偏斜** `compute_skew()`：
  - `|pos| < 0.75 × limit`：线性区，等同 v5.3 的 `int(alpha × pos)`
  - `|pos| ≥ 0.75 × limit`（即 pos≥60）：指数区，`raw = alpha × |pos| × exp(k × excess / limit)`，`k=2.0`
  - 关键数值：pos=60→skew=6，pos=70→skew=8，pos=78→skew=12
- **单边报价压制**：`|pos| ≥ 0.875 × limit`（即 pos≥70）时，压制增仓方向的 MM 挂单（`buy_cap=0` 或 `sell_cap=0`）
  - **仅作用于 Phase 2 Maker 层**，Phase 1 主动吃单逻辑不受影响（Patch 3 澄清）
- 移除 Module 2 和 Module 3 的冗余 `print` 语句，防止云端日志配额超限

**Why**:
- 云端实盘 PnL=2508 vs 本地 PnL=66k：回测器过度乐观，需压缩到可信量级以评估真实改进
- OSM 硬编码 FV=10000 在价格漂移（如跌至 9980）时导致持续买入、仓位套牢无法平仓
- 线性偏斜 `int(0.1 × 70) = 7` 不够强——指数偏斜在极端仓位时更激进地推动价格回归
- 单边压制防止在深度持仓时继续挂增仓方向的被动单，主动减少逆向选择风险

**Result** (V3 stochastic engine, random.seed=42):

| Day | 成交 ticks | Final PnL |
|-----|-----------|-----------|
| Day -2 | 1419 / 10000 | **+13,022.00** |
| Day -1 | 1437 / 10000 | **+13,636.00** |
| Day  0 | 1428 / 10000 | **+13,554.00** |
| **3日合计** | | **+40,212.00** |

注：成交 ticks 大幅下降（7000+ → 1400+）是 fill prob 降低的直接结果，属预期行为。

**Effective**: Yes — 回测器失真修复；OSM 仓位结尾不再钉在 ±80（各天末：47 / 27 / -42），库存偏斜防御效果提升
