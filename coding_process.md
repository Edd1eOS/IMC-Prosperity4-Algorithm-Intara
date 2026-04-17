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

## Entry 7 — Diagnostics-Only Batch: Attribution Instrumentation (2026-04-15)

**Date**: 2026-04-15

**Batch type**: DIAGNOSTICS ONLY — no strategy logic changed.

**What was instrumented**:

### backtester.py
- Added `p2_ppr_posted_below_30` counter to `_fresh_diag()` — tracks Phase 2 maker sell
  orders posted at PPR position ≤ -30 (intent volume, separate from fill volume)
- Added `pos_at_start` capture per product in `match_orders()` — position before any
  fills this tick, used as the posted-intent proxy for the new counter
- Added posted-intent counting loop: Phase 2 sell identified by `order.price > best_bid`
  (Phase 1 takers always have `order.price <= best_bid`; non-crossing clamp ensures Phase 2
  always has `order.price >= best_bid + 1`)
- Updated `_print_day_diagnostics()` to print all three Diag 2 lines:
  Phase-1 filled, Phase-2 posted (intent), Phase-2 filled

All other diagnostic infrastructure (Diag 1 asset MTM PnL, Diag 2 fill attribution,
Diag 3 saturation dwell, day boundary detection) was already present in backtester.py.

### round1_trader.py
- Set `DIAG_MODE = True` to enable Diagnostic 4 prints:
  `[DIAG_P1]` Phase 1b sell-taker events (bid, fv, delta, pos) at PPR pos ≤ -30
  `[DIAG_P2_POST]` Phase 2 sell posting events at PPR pos ≤ -30
- NOTE: DIAG_MODE must be reset to False before cloud submission

**Why no strategy logic was changed**:
The goal of this batch was purely diagnostic attribution — to determine whether PPR or OSM
is the dominant saturation bottleneck, and whether Phase 1 or Phase 2 is the larger
short-builder on PPR. No conclusions about the answers were assumed before running.
Changing strategy logic before reading diagnostics would make the diagnostic results
uninterpretable (we would not know whether any PnL change came from the instrumentation
or from the strategy change).

**Questions this batch was designed to answer**:
1. Which asset is the dominant saturation bottleneck: OSM or PPR?
2. On PPR, is Phase 1 taker or Phase 2 maker the larger contributor to short build-up?
3. Is short saturation severe enough to justify Change 1, Change 2, or both?
4. Should OSM be reprioritized before any PPR change?

**Diagnostic results summary** (full details in Backtest_Reports/Round1/diag_overview.txt):
- OSM is the dominant bottleneck: >=+80 for 596 ticks (2.0% avg), <=−80 for 206 ticks (0.7% avg)
- PPR is mild: <=−80 for only 7 ticks (0.02% avg) across all 3 days
- Phase 2 is the dominant PPR short-builder (3:1 ratio over Phase 1 at pos ≤ -30)
- All Phase 1 sells at pos ≤ -30 fired on marginal alpha (delta 1-2 only, no delta ≥ 5)
- OSM generated only +36 PnL across 3 days and was negative on Day 0 (-2780)

**Recommendation from diagnostics**: Re-evaluate OSM first (Change 4: OSM microprice
weight reduction 0.45 → 0.25). Do not implement Change 1 or Change 2 yet.

**Effective**: Yes — diagnostic instrumentation complete; all four diagnostic outputs
produced and saved.

## Entry 8 — Change 4: OSM Microprice Weight Reduction (v5.6) (2026-04-15)

**Date**: 2026-04-15

**Batch type**: Single targeted parameter change (Change 4 only).

**Diagnostics conclusion that justified this change**:

The 2026-04-15 diagnostics batch (Entry 7) produced the following findings:
- OSM is the dominant saturation bottleneck. OSM was at ≥+80 for 596 ticks across 3 days
  (2.0% average, peaking at 3.47% on Day 0). PPR was at ≤−80 for only 7 ticks (0.02% avg).
  OSM saturation is 85× worse than PPR at the hard limit.
- OSM MTM PnL was near-zero over 3 days (+36 total) and negative on Day 0 (−2,780).
  On Day 0, OSM was bi-directionally saturated: it reached ≥+80 (347 ticks) and ≤−80 (203 ticks)
  within the same day, indicating the FV mean-reversion signal failed completely.
- OSM ≥+70 dwell time averaged 5.5% of ticks — well above the plan's 5% materiality threshold.
- PPR short saturation (≤−70: 1.1% avg) was below threshold. PPR generates 99.9% of all PnL.
- The root cause hypothesis: OSM_MICRO_WEIGHT=0.45 makes the FV too reactive to transient
  book imbalances. A momentary microprice spike fires Phase 1 taker buys before the slow EMA
  (alpha=0.05, ~19 periods) can correct the FV anchor, driving the position into saturation.

**Exact parameters changed**:

| Parameter | Before (v5.5) | After (v5.6) | File | Line |
|---|---|---|---|---|
| `OSM_MICRO_WEIGHT` | 0.45 | 0.25 | round1_trader.py | 60 |
| `DIAG_MODE` | True | False | round1_trader.py | 82 |

DIAG_MODE was True only for the diagnostics batch. This restores the cloud-safe state.

**Behavioral meaning of the change**:

OSM fair value is computed as:
  `osm_fv = (1 - OSM_MICRO_WEIGHT) * slow_ema + OSM_MICRO_WEIGHT * microprice`

At 0.45: a 15-unit transient microprice deviation moves FV by ±6.75 units.
At 0.25: the same deviation moves FV by ±3.75 units — a 44% reduction in FV sensitivity.

The slow EMA (alpha=0.05, ~19 periods) now anchors 75% of FV instead of 55%.
Spurious Phase 1 taker buy triggers from downward microprice spikes are reduced.
Phase 1 sell triggers from upward spikes are similarly reduced.
The strategy's effective FV remains accurate for sustained price moves but no longer
overreacts to single-tick book imbalances.

**Why this should reduce OSM saturation risk**:
- Fewer Phase 1 taker buys triggered near the ±60–80 saturation zone
- FV less likely to drift away from the slow EMA anchor on transient events
- OSM bi-directional saturation (hit both ≥+80 and ≤−80 in same day) requires
  repeated FV miscalculations in both directions — reducing FV reactivity addresses both sides
- The change is cloud-transferable: Phase 1 taker fills are 100% in cloud and local;
  fewer taker triggers means fewer fills at the margin, independently of fill probability

**PPR logic intentionally left unchanged**:
No PPR parameters, thresholds, or logic were modified in this batch. The change is
strictly OSM-scoped. This preserves interpretability: any PnL or saturation change
observed after deployment is attributable solely to the OSM FV sensitivity reduction.

**Validation result** (2026-04-15, seed=42):

| Metric | v5.5 baseline | v5.6 tested | Verdict |
|---|---|---|---|
| OSM ≥+80 (3-day) | 596 ticks | 361 ticks (−39%) | ✓ long improved |
| OSM ≥+70 (3-day) | 1,638 ticks | 1,428 ticks (−13%) | ✓ modest |
| OSM ≤−80 (3-day) | 206 ticks | 280 ticks (+36%) | ✗ short worsened |
| OSM ≤−70 (3-day) | 508 ticks | 1,175 ticks (+131%) | ✗✗ short worsened sharply |
| OSM MTM PnL total | +36 | +130 | ✓ marginal |
| OSM Day -1 PnL | +1,703 | +2,605 | ✓ |
| OSM Day -2 PnL | +1,113 | −306 | ✗ turned negative |
| PPR / total PnL | — | — | ✗ INVALID (RNG state contamination) |

**Root cause of failure**: OSM_MICRO_WEIGHT is a symmetric parameter. Reducing it makes FV less
reactive to ALL transient book moves, in both directions. When the market spikes upward, the lower
FV causes more bids to appear "above FV", triggering Phase 1 sell takers aggressively — this drove
Day -1 OSM ≤-70 from 20 ticks to 554 ticks (27×). The parameter redistributed saturation from long
to short without eliminating it. Net total extreme-saturation (≥+80 + ≤-80): 802 → 641, only −20%.

**Note on PPR/total PnL comparison**: The PPR and total PnL numbers differ wildly between v5.5
and v5.6 (e.g., Day -2 PPR: 9,337 → 18,490). This is a RNG state artifact, not real behavior.
Different OSM taker order counts per tick shift the random() call sequence for PPR fills. Only
OSM-specific metrics are valid cross-version comparisons.

**Decision**: REVERTED. OSM_MICRO_WEIGHT restored to 0.45. Change 4 in this form (0.25) is a
FAIL — it shifted saturation from long to short side without structural improvement.

**Parameter state after revert**: OSM_MICRO_WEIGHT = 0.45, DIAG_MODE = False (cloud-safe).

**Next batch options**:
- Path A: Try OSM_MICRO_WEIGHT = 0.35 (moderate reduction; may reduce long saturation with less
  symmetric short saturation blowup, since the effect is smaller per unit of market move)
- Path B: Add OSM Phase 1 bilateral position gate (taker_buy_gate = +40, taker_sell_gate = −40),
  directly capping how deep Phase 1 can push OSM position in either direction, independent of FV.

## Entry 9 — Change 4 Experiment Closed / Rollback Confirmed (2026-04-15)

**Date**: 2026-04-15

**Batch type**: Rollback confirmation and experiment closure. No new logic introduced.

**What was rolled back**:
- `OSM_MICRO_WEIGHT`: reverted from 0.25 (Change 4 test value) back to **0.45** (v5.5 baseline)
- `DIAG_MODE`: confirmed **False** (was already False; cloud-safe)
- All other parameters unchanged throughout

The v5.6 changelog comment block in `round1_trader.py` is retained as an inline record of the
failed experiment. The active trading logic is v5.5.

**Why rollback was necessary**:
Change 4 (OSM_MICRO_WEIGHT 0.45 → 0.25) produced the following local test outcome:
- OSM long saturation (≥+80) reduced: 596 → 361 ticks (−39%) — intended improvement
- OSM short saturation (≤−70) worsened: 508 → 1175 ticks (+131%) — unintended regression
- Day -1 OSM ≤−70 exploded: 20 → 554 ticks (+27×) — single worst-case regression
- OSM total MTM PnL: +36 → +130 — improvement negligible
- Cloud PnL also deteriorated relative to the prior baseline (confirmed by user)

Root cause: `OSM_MICRO_WEIGHT` is symmetric. Reducing it dampens FV reactivity in both
directions equally. When the market spikes upward, the lower FV causes Phase 1 sell takers to
trigger more aggressively — building short positions that saturate. The parameter cannot be
used alone to fix one-sided (long) saturation without creating opposite (short) saturation.

**Evidence preserved for future batches**:
- Local test raw output: `Backtest_Reports/Round1/v5.6_Change4/raw_day_{minus2,minus1,0}.txt`
- Per-day diagnostic summaries: `diag_summary_day_{minus2,minus1,0}.txt`
- Diagnostic overview with analysis: `diag_overview.txt`
- Coding process entries (Entry 8 + 9): full failure analysis and root cause
- Testing execution log (Run 14 + rollback record): before/after metrics table

**Active baseline after rollback**:
v5.5 logic, confirmed by safety check (13 parameters verified against expected values):
  `OSM_MICRO_WEIGHT = 0.45`, `DIAG_MODE = False`, all other constants unchanged.
File is cloud-submission safe.

**Change 4 experiment: CLOSED.**

**Next candidate directions** (to be decided in a separate batch):

Path A — OSM_MICRO_WEIGHT = 0.35 (moderate reduction):
  Smaller step than 0.25. May yield partial long saturation reduction without triggering
  the symmetric short saturation blowup observed at 0.25. Lower risk, but still uses the
  same symmetric mechanism — may simply produce a smaller version of the same failure.

Path B — OSM bilateral Phase 1 position gate (preferred candidate):
  Add `taker_buy_gate = +40` and `taker_sell_gate = −40` inside `aggressive_take_and_mm`
  for OSM only. When `sim_pos >= +40`, Phase 1 taker buys stop. When `sim_pos <= −40`,
  Phase 1 taker sells stop. This caps how deep Phase 1 drives OSM inventory in either
  direction, regardless of FV computation. Cloud-transferable (Phase 1 = 100% fill in
  cloud and local). Can be set asymmetrically (e.g., buy_gate = +40, sell_gate = −50)
  to match the observed asymmetry in saturation data. Does not touch FV, skew, or maker
  logic — cleanly isolated and interpretable.

## Entry 10 — v5.7: Path B — OSM Phase 1 双向仓位门控

**Date**: 2026-04-15

**Batch type**: Path B — 针对 OSM 的 Phase 1 吃单深度直接门控。单一、定向、机制级别的干预。

**Change 4 被拒的原因（不再试 Path A 的理由）**:

Change 4 实验（v5.6，`OSM_MICRO_WEIGHT 0.45 → 0.25`）已明确证明 `OSM_MICRO_WEIGHT`
是对称参数：降低它后，FV 对上行脉冲同等减感，导致 Phase 1 卖单大量触发、短侧饱和爆炸。
Day -1 OSM ≤-70 从 20 → 554 ticks (+27倍)，比原始长侧问题更严重。
Path A（0.35 中间值）使用同一个有缺陷的机制，只是步长更小；它无法从机制上隔离单侧饱和，
只会产生"副作用稍小的 Change 4 重演"。Path B 完全绕过 FV 计算，直接在仓位层面截断 Phase 1
推力，是更干净、更可解释、云端可移植的改动。

**新增参数（仅 OSM 调用处传入，PPR 维持 None）**:

| 参数 | 值 | 含义 |
|-----|-----|------|
| `taker_buy_gate` | +40 | sim_pos >= +40 时 Phase 1a 停止主动买入吃单 |
| `taker_sell_gate` | -40 | sim_pos <= -40 时 Phase 1b 停止主动卖出吃单 |

**代码变更明细**:

| 位置 | 改动 |
|------|------|
| `aggressive_take_and_mm()` 函数签名 | 新增 `taker_buy_gate: int | None = None` 和 `taker_sell_gate: int | None = None` 两个可选参数 |
| Phase 1a 循环（`ask_price` 遍历）| FV 检查后增加：`if taker_buy_gate is not None and sim_pos >= taker_buy_gate: break` |
| Phase 1b 循环（`bid_price` 遍历）| FV 检查后增加：`if taker_sell_gate is not None and sim_pos <= taker_sell_gate: break` |
| Module 2 OSM 调用处 | 新增 `taker_buy_gate=40, taker_sell_gate=-40` 关键字参数 |
| Module 3 PPR 调用处 | 未变动，两参数默认为 `None`（行为不变） |

**期望效果（OSM 饱和与前半段容量）**:

1. Phase 1 每个 tick 最多将 OSM 推至 ±40（由 sim_pos 追踪，填单逻辑不变）
2. ±40 到 ±80 区间只能通过 Phase 2 被动做市（Maker，填单率约 3%）触达，
   天然形成速率节流，极端区域停留时间应大幅缩短
3. 当市场需要反向平仓时，OSM 从 ±40 出发（而非 ±80），有更大空间做双向做市，
   预计前半段 PnL 曲线不再呈长时间水平段

**刻意保持不变的部分**:
- `OSM_MICRO_WEIGHT`, `OSM_EMA_ALPHA`, `OSM_FV` 和所有 FV 公式 — 不变
- `compute_skew()`, `SKEW_K`, `SKEW_THRESHOLD`, `ONE_SIDE_FRAC` — 不变
- `MAX_MM_LOT`, `PPR_LIMIT`, `EMA_ALPHA`, `MICRO_WEIGHT` 等所有其他参数 — 不变
- DIAG_MODE = False（云端安全）
- PPR 的整个 Module 3 逻辑 — 完全不变（taker gate 均为 None）

**Cloud result**: FAIL — PnL = 2205 (vs v5.4 target 2441). Same as v5.6 Change 4.
Root cause: gate was applied on top of v5.5 parameters; could not exceed the v5.5 performance ceiling.
**Decision**: REVERTED in v5.8 along with all v5.5 parameter changes.

## Entry 11 — v5.8: 完整回滚至 v5.4 参数基线

**Date**: 2026-04-15

**Batch type**: 回滚。无新策略逻辑。

**回滚动机**:

v5.6（Change 4）和 v5.7（Path B）均在 v5.5 参数基础上改动，云端 PnL 均为 ~2205，
低于 v5.4 基准的 2441。根本原因是 v5.5 引入的三个参数（见下表）把云端性能从 2441
压低至 ~2205，后续所有 v5.5 基础上的实验都无法突破这个上限。

**回滚内容**:

| 参数 | v5.5（被回滚值）| v5.8（恢复值）| 恢复依据 |
|------|--------------|-------------|---------|
| `OSM_MICRO_WEIGHT` | 0.45 | **0.20** | v5.4 原始值 |
| `SKEW_K` | 3.0 | **2.0** | v5.4 原始值 |
| `SKEW_THRESHOLD` | 0.60 | **0.75** | v5.4 原始值 |
| Phase 1 gate (v5.7) | taker_buy_gate=40, taker_sell_gate=-40 | **移除** | v5.7 REVERTED |

**保留不变（v5.4 已有架构）**:
- 动态 OSM FV（慢EMA + microprice 混合），`fv_int = round(fv)` bug fix
- `osm_history` 跨 tick 状态持久化
- `microprice` 函数参数（无害，不影响行为）
- DIAG_MODE = False（云端安全）

**本地验证**（seed=42，v5.4 基准逐位吻合）:

| Day | v5.4 基准 | v5.8 结果 | 末仓 OSM/PPR |
|-----|----------|----------|-------------|
| Day -2 | +13,022 | +13,022 | OSM=+47, PPR=+75 |
| Day -1 | +13,636 | +13,636 | OSM=+27, PPR=-71 |
| Day  0 | +13,554 | +13,554 | OSM=-42, PPR=-33 |
| **合计** | **+40,212** | **+40,212** | — |

本地结果完全吻合，证明 v5.8 精确还原了 v5.4 交易行为。

**云端目标**: 恢复至 2441 水平。

**Effective**: 待云端验证

---

## Entry 12 — v6.0: Three-Layer Upgrade (Kalman FV + Position-Aware Phase 1 + AS Dynamic Spread)

**Date**: 2026-04-15

**Batch type**: 重大升级 — 针对 OSM 饱和、冷启动死区、Phase 2 点差收益三项核心瓶颈。

**Motivation**: 云端 PnL 2441 / 100K ticks，目标 ≥ 4000。PnL 曲线 0–40K ticks 平滞（占 40%
时间无收益），40–100K 急速拉升。理论上若能填平死区，目标为 2441/0.6 ≈ 4068 可达。

**三项核心改动**:

### 改动 1 — OSM FV: EMA混合 → 1D Kalman Filter

- **替换**: `FV = 0.8×EMA(α=0.05) + 0.2×microprice`（有效α≈0.24，过快追价）
- **新增**: `kalman_update_1d(x, P, z, Q=0.005, R=4.0)`，P₀=25
- 冷启动：K₀ = 25/(25+4) ≈ 0.86，第1个tick立即收敛到首次观测值
- 稳态：K ≈ 0.034，比原EMA慢7×，FV牢锚在10000附近
- 预期效果：消灭开盘30tick"热机死区"，同时减少FV漂移至10001导致的虚假吃单

### 改动 2 — Phase 1 仓位感知阈值（OSM专属，PPR零影响）

- 新增参数 `OSM_TAKER_ALPHA = 0.1`（与 OSM_ALPHA 一致）
- Phase 1a 买入阈值：`fv_int - int(0.1 × max(sim_pos, 0))`
  - pos=0: 阈值=fv_int（无变化）
  - pos=+40: 阈值=fv_int-4（需4tick优势才买）
  - pos=+80: 阈值=fv_int-8（OSM std=5，-8tick极罕见 → 几乎停止买入）
- Phase 1b 卖出阈值：`fv_int + int(0.1 × max(-sim_pos, 0))`（对称）
- PPR 调用传 `taker_alpha=0.0` → 阈值等价于原 fv_int，完全无影响
- 预期效果：OSM 长仓饱和从 596 ticks/100K → <150 ticks/100K

### 改动 3 — Phase 2 AS 动态点差（双资产）

- 新增 `compute_micro_vol(prices, lookback=10)` 计算滚动σ
- 公式：`δ_raw = max(1, round(γ × σ))`, `δ_eff = min(δ_raw, (best_ask-best_bid)//2)`
- **OSM**: `OSM_AS_GAMMA=2.0` + 书册上限=1（OSM买卖差通常=2） → δ恒为1（零副作用）
- **PPR**: `PPR_AS_GAMMA=0.15` + 宽买卖差 → σ≥10时δ→2，同等成交概率(30%)但每笔多赚1tick
- 新增 `half_spread` 参数加入 `aggressive_take_and_mm()` 签名（默认=1，向后兼容）
- 预期效果：PPR Phase 2 高波动期收益约翻倍

**新增常量**:

| 常量 | 值 | 说明 |
|------|---|------|
| `OSM_KALMAN_Q` | 0.005 | Kalman过程噪声 |
| `OSM_KALMAN_R` | 4.0 | Kalman观测噪声 |
| `OSM_KALMAN_P0` | 25.0 | Kalman初始协方差 |
| `OSM_TAKER_ALPHA` | 0.1 | Phase 1 仓位惩罚系数 |
| `OSM_AS_GAMMA` | 2.0 | OSM AS点差风险厌恶系数 |
| `PPR_AS_GAMMA` | 0.15 | PPR AS点差风险厌恶系数 |
| `AS_VOL_LOOKBACK` | 10 | AS微观波动率滚动窗口 |

**本地验证目标**: 3天总 PnL > 48,000（v5.8基线 40,212，+20%）

**云端目标**: ≥ 3,200 XIREC / 100K ticks，力争 ≥ 4,000

**后参数调优指导**:
- 若OSM仍饱和：将 `OSM_TAKER_ALPHA` 从 0.1 提升至 0.15
- 若PPR spread始终=1：将 `PPR_AS_GAMMA` 从 0.15 提升至 0.20
- 若Kalman FV追踪过慢：将 `OSM_KALMAN_Q` 从 0.005 提升至 0.01

**云端实测结果**: **3,352 XIREC / 100K ticks**（v5.8基线 2,441，+**37.3%**）✅
- 三项改动均有效，无需回滚
- 距离 4,000 目标还差 648（-16.2%），下一步聚焦进一步压缩OSM饱和或提升PPR点差

**Effective**: 2026-04-16 云端验证通过

---

## Entry 13 — v7.0: 五层微观结构升级（Active Unwind + Regime Switching + OBI）

**Date**: 2026-04-16

**Batch type**: 重大升级 — 针对 v6.0 的两个核心微观结构缺陷（OSM 库存死锁 + PPR 趋势滞后）。

**动机（v6.0 后的残余缺陷）**:
- 云端 PnL 3352 / 100K，目标 4000+（差 648，-16.2%）
- OSM 在 |pos|≥80 时进入库存死锁：指数偏斜使挂单价格严重偏离市场，既无法吃点差也无法平仓，资金周转率降零
- PPR 在强趋势行情中：EMA 持续滞后于市价，Phase 1b 不断触发逆势做空，迅速钉死在 -80，错失趋势 Beta 并承担摩擦成本

---

### 改动 1 — OSM Active Unwind (Phase 1c)

**核心数学**：当 `sim_pos ≥ OSM_UNWIND_THRESH (=70)` 时：
```
unwind_sell = min(limit + sim_pos, OSM_UNWIND_LOT, avail_at_best_bid)
place Order(symbol, best_bid, -unwind_sell)   # taker：100% 成交
```
对称地，`sim_pos ≤ -70` 时在 best_ask 买入。

**代价分析**：每手损失约 1 tick（OSM 点差 ≈ 2，半点差 = 1）。死锁期间每 tick 收益 = 0，而主动减仓期间每手成交可快速释放后续收益空间。以 5 手/tick 的速度，从 +80 减至 +70 约需 2 个 tick（10 XIREC 点差成本），解锁后的 MM 收益远超此成本。

**新增常量**：`OSM_UNWIND_THRESH = 70`, `OSM_UNWIND_LOT = 5`

---

### 改动 2 — PPR Regime Switching（状态机）

**核心数学**：线性回归斜率估计（最小二乘）：
```
slope = Σ[(i - x̄)(pᵢ - ȳ)] / Σ[(i - x̄)²]   (过去 20 tick)
```
PPR 期望漂移 ≈ 0.1/tick，阈值 0.06 = 60% 的期望信号强度。

**状态转移**：
```
slope >  0.06 → ppr_trend_cnt = max(0, cnt) + 1
slope < -0.06 → ppr_trend_cnt = min(0, cnt) - 1
|slope| ≤ 0.06 → ppr_trend_cnt = 0

cnt ≥ +3 → TREND_UP  (skip_phase1_dir = +1: 跳过所有卖出)
cnt ≤ -3 → TREND_DOWN (skip_phase1_dir = -1: 跳过所有买入)
otherwise → MM 模式 (skip_phase1_dir = 0)
```

**预期效果**：TREND_UP 模式下 PPR 不再累积空仓，彻底解决趋势行情中的 -80 锁死问题。

**新增常量**：`PPR_SLOPE_WINDOW=20`, `PPR_SLOPE_THRESH=0.06`, `PPR_TREND_CONFIRM=3`

---

### 改动 3 — PPR taker_alpha = 0.1（原为 0.0）

与 OSM 完全对称的 Phase 1 仓位感知机制（v6.0 已验证有效）：
```
Phase 1b sell threshold = fv_int + int(0.1 × max(-sim_pos, 0))
pos = -70 → threshold = fv + 7   (需 bid > fv+7 才触发，大幅压制深度建空)
```
在非趋势日（状态机未激活时）作为第一道防线。

---

### 改动 4 — OBI 对冲选择过滤（Phase 2 only）

**核心数学**：
```
OBI = (Σ|V_bid_i| - Σ|V_ask_i|) / (Σ|V_bid_i| + Σ|V_ask_i|)
OBI ∈ [-1, +1]
```
使用全簿深度（非仅 best bid/ask），更能反映真实买卖压力。

**过滤规则（仅 Phase 2 Maker 层）**：
```
OBI > +0.7 → skip_p2_sell = True   (强买压：做市卖单将被逆向选择)
OBI < -0.7 → skip_p2_buy  = True   (强卖压：做市买单将被逆向选择)
```
Phase 1 Taker 层不受影响（Phase 1 本身是吃单，方向选择已由 FV 决定）。

---

### 改动 5 — PPR Active Unwind（与 OSM 对称）

`PPR_UNWIND_THRESH=70`, `PPR_UNWIND_LOT=5`。当 PPR 仓位 ≥+70 或 ≤-70 时，Phase 1c 以 taker 价格强制减仓，防止 PPR 因趋势超冲到达硬限后无法退出。

---

### 架构影响

`aggressive_take_and_mm()` 新增参数：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `unwind_thresh` | int \| None | None | Phase 1c 触发阈值 |
| `unwind_lot` | int | 5 | Phase 1c 每 tick 最大手数 |
| `skip_phase1_dir` | int | 0 | +1=跳过卖, -1=跳过买, 0=正常 |
| `obi` | float | 0.0 | Phase 2 OBI 过滤值 |

新增辅助函数：
- `compute_obi(order_depth)` — 全簿 OBI 计算
- `compute_slope(prices, window)` — 线性回归斜率

移除：
- `microprice` 参数（在 v6.0 已停用，本次清理）
- `JUMP_THRESHOLD` 常量（同上）

新增状态（traderData）：
- `ppr_trend_cnt` — PPR 状态机有符号计数器（正=上升趋势，负=下降趋势）

---

### 校验标准（Validation Criteria）

| 指标 | 失败阈值 | 说明 |
|------|----------|------|
| OSM ≥+80 停留时间 | > 总 tick 数 5% | 死锁未解除 |
| PPR ≤-80 停留时间 | > 总 tick 数 5% | 趋势滞后未修复 |
| 本地 PnL/Tick | < 4.05 (折算) | 整体效率下滑 |
| 3日合计本地 PnL | < 48,000 | 低于 v6.0 预期基线 |

**一键回滚方案**（若校验失败）：
```
git checkout 8167a41 -- round1_trader.py
```
commit `8167a41` 是 v6.0 的精确快照（云端验证：3352/100K）。

**Effective**: 待本地回测 + 云端验证

## Entry 14 — v8.0: PPR Drift Maximization + OSM Capacity Upgrade

**Date**: 2026-04-17

**Batch type**: Major upgrade — PPR position-maximizing overhaul + OSM parameter tuning.

**Motivation (v7.0 post-mortem from 198447.log)**:

v7.0 cloud PnL = 4,597 XIREC (OSM=1,683, PPR=2,914) over 1K test iterations.
Detailed trade log analysis revealed PPR as the dominant bottleneck:

- PPR made only 16 SUBMISSION trades in 1000 iterations (14 buys, 2 sells)
- PPR final position = +50 out of +/-80 limit (62.5% utilization)
- PPR dead zones: 4 gaps totaling 568 iterations (56.8% of run idle)
  - Longest dead zone: t=68.3K -> t=87.8K (195 iterations, 19.5% of run)
- PPR counterproductive 15-unit sell at t=65.7K (sold at 12060, PPR ended at 12100, ~600 XIREC lost)
- PPR Phase 1a buy threshold with taker_alpha=0.1 at pos=+40: `ask < fv-4`, almost never fires
- PPR EMA(alpha=0.2) lags true price by ~5+ points, FV systematically below market

OSM secondary issue:
- OSM 90-100K delta collapsed to 35.4 (vs average ~170 per 10K block)
- Kalman Q=0.005 too conservative, FV slow to adapt in late-game micro-regime changes

Ideal PPR scenario: Hold +80 from tick ~5 to tick 1000, drift income = 80 x 0.1 x 995 = 7,960 XIREC.
Current PPR = 2,914. Theoretical ceiling improvement: +5,046 XIREC.

---

### Changes in round1_trader.py

#### Change 1 — PPR FV Drift Bias (fastest tracking + upward bias)

| Parameter | Before (v7.0) | After (v8.0) | Behavioral meaning |
|---|---|---|---|
| `EMA_ALPHA` | 0.2 | **0.6** | EMA half-life: ~4.5 ticks to ~1.2 ticks. Eliminates 5+ point FV lag |
| `MICRO_WEIGHT` | 0.3 | **0.7** | FV = 0.3 x EMA + 0.7 x micro (was 0.7 x EMA + 0.3 x micro) |
| `PPR_DRIFT_BIAS` | N/A | **10** (NEW) | FV = formula + 10. Biases FV above market to trigger Phase 1a buys |

With PPR half-spread ~7-8: `fv = microprice + 10 > best_ask = microprice + 7`.
Phase 1a condition `ask < fv_int` now fires every tick with ask volume.
Cost per lot: ~6-7 points above midprice. Break-even: ~60-70 ticks.

#### Change 2 — PPR Permanent TREND_UP

Replaced v7.0 regime switching decision block with `skip_dir = 1` (force TREND_UP permanently).
v7.0 slope/ppr_trend_cnt computation still runs (state preserved for rollback).

Eliminates: Phase 1b sells (the t=65.7K 15-unit dump) + Phase 2 MM sell orders.

#### Change 3 — PPR_TAKER_ALPHA: 0.1 to 0.0

v7.0: Phase 1a buy threshold = `fv - int(0.1 * max(pos, 0))`. At pos=+40: `fv - 4`.
v8.0: buy threshold = `fv`. No position penalty. Continuous buying until position limit.

#### Change 4 — PPR unwind_thresh: 70 to None

v7.0: pos >= +70 triggers Phase 1c sell at best_bid to unwind. Counterproductive for trend asset!
v8.0: `unwind_thresh=None` in PPR call. Hold longs to maximize drift income.
Constants `PPR_UNWIND_THRESH=70`, `PPR_UNWIND_LOT=5` preserved for rollback.

#### Change 5 — OSM_KALMAN_Q: 0.005 to 0.015

Steady-state Kalman gain K = sqrt(Q/R) ~ sqrt(0.015/4.0) ~ 0.061 (was 0.035).
FV adapts ~1.75x faster to micro-regime shifts. Target: reduce 90-100K PnL collapse.

#### Change 6 — OSM capacity increase

| Parameter | Before | After | Effect |
|---|---|---|---|
| `MAX_MM_LOT` | 15 | **20** | Phase 2 MM orders up to 20 lots |
| `OSM_UNWIND_LOT` | 5 | **10** | Phase 1c unwind 10 lots/tick. +80 to +70 in 1 tick |

---

### What was NOT changed

- `OSM_KALMAN_R`, `OSM_KALMAN_P0`, `OSM_TAKER_ALPHA` -- unchanged
- `OSM_AS_GAMMA`, `PPR_AS_GAMMA`, `AS_VOL_LOOKBACK` -- unchanged
- `SKEW_K`, `SKEW_THRESHOLD`, `ONE_SIDE_FRAC` -- unchanged
- `aggressive_take_and_mm()` function body -- unchanged (all changes via parameters)
- Module 4 position clamp safety net -- unchanged
- DIAG_MODE = False (cloud-safe)

---

### Expected Performance

| Metric | v7.0 (actual) | v8.0 (expected) | Delta |
|---|---|---|---|
| PPR position at t=10K | +6 | >+60 | Sprint to near-max |
| PPR trade count | 16 | >30 | Continuous buying |
| PPR sells | 2 (incl 15-lot dump) | 0 | Eliminated |
| PPR PnL | 2,914 | ~6,000-7,500 | +3,000-4,600 |
| OSM PnL | 1,683 | ~1,900-2,100 | +200-400 |
| Total PnL | 4,597 | ~8,000-10,000 | ~2x |

**Effective**: Yes -- Cloud PnL = **9,028 XIREC** (+96.3% vs v7.0's 4,597). Submission ID 247252.
Curve nearly perfectly linear (drift-dominated). Projected final scoring (10K iter): ~88,500 XIREC (best estimate).

### Rollback Plan

Revert 10 parameter/logic changes to restore exact v7.0 behavior:
```
EMA_ALPHA=0.2, MICRO_WEIGHT=0.3, MAX_MM_LOT=15, PPR_TAKER_ALPHA=0.1,
PPR_DRIFT_BIAS -> remove, OSM_KALMAN_Q=0.005, OSM_UNWIND_LOT=5,
skip_dir -> restore regime switching block, unwind_thresh=PPR_UNWIND_THRESH,
remove PPR_DRIFT_BIAS from FV formula
```

**Result**: Pending cloud verification

**Effective**: Pending

## Entry 15 — v8.1: OSM Parameter Tuning + PPR Entry Cost Reduction

**Date**: 2026-04-17

**Batch type**: Parameter tuning — OSM is the only optimization lever (PPR at theoretical ceiling).

**Motivation (247252.log deep analysis)**:

v8.0 cloud PnL = 9,028 XIREC (OSM=1,688, PPR=7,340) over 1K test iterations.
Second cloud run (244581) = 9,828, indicating ~8.6% run-to-run variance.

PPR analysis — **at theoretical maximum, no optimization needed**:
- Position filled to +80 in 6 ticks (t=0→t=600), entry cost ~604 XIREC
- 993/999 ticks produce exactly +8.0 XIREC/tick (80 × drift 0.1)
- 0 idle ticks, 0 negative deltas after t=600
- Steady-state rate: 8.0 XIREC/tick → projected 10K iter PPR = ~79,340

OSM analysis — **primary bottleneck, volatile and underperforming**:
- PnL = 1,688 (18.7% of total), rate = 1.69/tick
- Per-10K block: 133, 201, 186, 85, 163, 248, 204, 285, 126, 56 (stdev ~70)
- 90-100K block = 56 XIREC (worst block, large loss clustering)
- 111/999 ticks produce >5 XIREC loss (11.1% of ticks)
- Typical spread: 16 (62.3%), 18 (13.1%), 19 (12.8%)
- Current AS half_spread = round(2.0 × vol) ≈ 10, too conservative for spread=16 market

---

### Changes in round1_trader.py

#### Change 1 — OSM_AS_GAMMA: 2.0 → 1.4

AS half_spread = round(1.4 × vol) ≈ 7 (was ~10).
With market spread=16, our bid/ask goes from mid±10 to mid±7.
Tighter quotes = higher fill probability, closer to best bid/ask.
Risk: increased adverse selection if FV estimate lags.

#### Change 2 — OSM_KALMAN_Q: 0.015 → 0.025

Steady-state gain K = sqrt(0.025/4.0) ≈ 0.079 (was 0.061).
FV tracks mid price ~30% faster. Target: reduce 90-100K block PnL collapse.

#### Change 3 — OSM_UNWIND_THRESH: 70 → 60

Earlier forced unwind trigger. Reduces time spent at extreme positions
where adverse price movement has outsized PnL impact.

#### Change 4 — OSM_TAKER_ALPHA: 0.1 → 0.05

Phase 1 buy threshold: fv - int(0.05 × pos) instead of fv - int(0.1 × pos).
At pos=+40: from fv-4 to fv-2. More mean-reversion trades executed.

#### Change 5 — MAX_MM_LOT: 20 → 25

Order book L1 depth commonly 10-28 lots. Larger MM orders capture more spread income per tick.

#### Change 6 — PPR_DRIFT_BIAS: 10 → 7

PPR ask - mid typically 6-8. Bias=7 still triggers Phase 1a buys every tick.
Cost saving: ~3 points/unit × 80 units = ~240 XIREC less entry cost.

---

### What was NOT changed

- All PPR structural logic (TREND_UP, no unwind, taker_alpha=0.0) — untouched, at theoretical max
- EMA_ALPHA, MICRO_WEIGHT — PPR FV formula unchanged except bias
- OSM_KALMAN_R, OSM_KALMAN_P0 — unchanged
- OSM_UNWIND_LOT (=10) — unchanged
- aggressive_take_and_mm() function body — unchanged
- Module 4 position clamp safety net — unchanged
- DIAG_MODE = False (cloud-safe)

---

### Expected Performance

| Metric | v8.0 (247252 actual) | v8.1 (expected) | Delta |
|---|---|---|---|
| OSM PnL | 1,688 | ~2,200-2,500 | +500-800 (+30-50%) |
| PPR PnL | 7,340 | ~7,540-7,580 | +200-240 (entry cost saving) |
| Total PnL | 9,028 | ~10,000-11,000 | +10-20% |

### Rollback Plan

Revert 6 parameters to restore exact v8.0 behavior:
```
OSM_AS_GAMMA=2.0, OSM_KALMAN_Q=0.015, OSM_UNWIND_THRESH=70,
OSM_TAKER_ALPHA=0.1, MAX_MM_LOT=20, PPR_DRIFT_BIAS=10
```

**Result**: Cloud PnL = 8,774 XIREC (-2.8% vs v8.0's 9,028). Regression.

**Effective**: No -- Rolled back to v8.0. Tighter OSM quotes (AS_GAMMA 1.4) likely increased adverse selection losses more than fill-rate gains.

## Entry 16 — v8.0a: PPR Drift Bias Isolation Test (FAILED)

**Date**: 2026-04-17

**Batch type**: Single-variable isolation test — PPR_DRIFT_BIAS 10 to 7.

**Motivation**: v8.1 changed 6 variables simultaneously, making failure unattributable. This test isolates the one theoretically-certain improvement: reducing PPR entry cost by lowering drift bias.

### Changes

- PPR_DRIFT_BIAS: 10 to 7 (only change)

### Result

Cloud PnL = 9,131 XIREC (Submission 248418/251114). PPR: 7,443 (+103 vs 7,340). OSM: 1,688 (identical).

Key finding: **OSM PnL was tick-for-tick identical** across 247252 and 251114, proving these two runs used the same market data. The 244581 submission (misread as 9,828, actual unknown) used a different dataset.

PPR delta breakdown: entry cost saved +143, but 5 extra build ticks lost -40 drift = net +103.

**Effective**: No -- Rolled back to v8.0. +103 (+1.1%) too small to justify. bias=7 is at the critical edge (ask~mid+6-8), risks build failure on wider-spread datasets. bias=10 has 3-4 point safety margin.

## Entry 17 — v8.0b: OSM Dual-Layer Maker

**Date**: 2026-04-17

**Batch type**: Structural change — add Layer 2 wider maker quotes for OSM only.

**Motivation**:

v8.1 (6 OSM parameter changes) failed: PnL -2.8%. v8.0a (PPR-only) gave +1.1%, too small.
OSM simple parameter tuning has hit a wall. Structural change needed.

Key insight from 247252: OSM typical spread = 16 (62.3%). Layer 1 quotes at FV ± ~8 (eff_spread).
There is room for a second, wider layer at FV ± ~12 that captures volatility-spike fills
without competing with or affecting Layer 1.

---

### Changes in round1_trader.py

#### Change 1 — New constants OSM_L2_OFFSET=4, OSM_L2_LOT=10

Layer 2 quotes at FV ± (eff_spread + 4) - skew.
With eff_spread ≈ 8: L2 bid ≈ 9988 (L1 ≈ 9992), L2 ask ≈ 10012 (L1 ≈ 10008).
L2 sits at the 2nd level of the order book, capturing fills only during price spikes.
L2 lot = 10 (half of MAX_MM_LOT=20).

#### Change 2 — Function signature: +layer2_offset, +layer2_lot

Two new optional parameters (default 0 = disabled). Only OSM call passes nonzero values.
PPR call unchanged (defaults to 0, Layer 2 never executes).

#### Change 3 — Phase 2b logic block

After Layer 1 orders, adds Layer 2 wider quotes with:
- Same non-crossing clamp (mm_bid_L2 < best_ask, mm_ask_L2 > best_bid)
- Same one-side threshold suppression (pos ≥ 87.5% limit → no buy/sell)
- Same OBI + direction filtering
- Module 4 position clamp handles total order capacity

#### Change 4 — OSM call site: pass layer2_offset and layer2_lot

### What was NOT changed

- Layer 1 logic: completely untouched (same prices, same lot sizes)
- All PPR logic: untouched (layer2_offset defaults to 0)
- All parameters: no constants changed
- Phase 1a/1b/1c: untouched
- Module 4 safety net: untouched

---

### Expected Performance

| Metric | v8.0 (actual) | v8.0b (expected) | Delta |
|---|---|---|---|
| OSM PnL | 1,688 | ~1,900-2,100 | +200-400 (L2 fills) |
| PPR PnL | 7,340 | 7,340 | 0 (unchanged) |
| Total PnL | 9,028 | ~9,200-9,400 | +2-4% |

### Rollback Plan

Remove `layer2_offset` and `layer2_lot` from OSM call (revert to defaults 0,0).
Phase 2b block becomes dead code (safe). Or remove Phase 2b block + constants + params.

**Result**: Cloud PnL = 9,028 XIREC (Submission 252480). OSM=1,688.4375, PPR=7,340. Tick-for-tick identical to v8.0 (247252). Layer 2 received 0 fills across 1,000 ticks.

Root cause: L2 quotes at FV ± ~12 were deeper than the typical best bid/ask (~9992/~10008). In this low-volatility market data, price never reached L2 depth. L2 was effectively dead orders.

**Effective**: No -- Rolled back to v8.0. L2 offset too wide for this market; 0 incremental fills.
