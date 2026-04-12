# Testing Execution Log

## Run 1 — Skeleton Phase (2026-04-09)

**Method**: Manual code review against platform contract

**Checks**:
- [x] `Trader` class exists, no-arg constructor
- [x] `run(self, state: TradingState)` method exists
- [x] Returns `(dict[Symbol, list[Order]], int, str)`
- [x] Handles empty order book (guard: `if order_depth.sell_orders` / `if order_depth.buy_orders`)
- [x] Position limit check before placing orders
- [x] Only imports from `datamodel` (platform-provided)
- [ ] Backtester run (not yet installed)

**Result**: PASS (manual review). Awaiting backtester verification.

**Failures**: None.

## Run 2 — Market Making Phase (2026-04-09)

**Method**: Manual code review

**Checks**:
- [x] Buy order placed at best_bid (not best_ask)
- [x] Sell order placed at best_ask (not best_bid)
- [x] Empty book handled: `best_bid`/`best_ask` = None, order skipped
- [x] Position limit check unchanged and correct
- [x] Print log line per product per tick
- [x] Return type unchanged: `(dict, int, str)`
- [ ] Backtester run (not yet installed)

**Result**: PASS (manual review). Awaiting backtester PnL check.

**Failures**: None.

## Run 3 — Competitive Market Making Phase 2.5 (2026-04-09)

**Method**: Manual code review

**Checks**:
- [x] When spread > 1: buy at best_bid + 1, sell at best_ask - 1
- [x] When spread <= 1: fallback to best_bid / best_ask
- [x] Crossing guard: if my_bid >= my_ask, revert to original prices
- [x] Empty book handled: best_bid/best_ask = None, order skipped
- [x] Position limit check unchanged and correct
- [x] Log line includes both market prices (bid/ask) and chosen prices (my_bid/my_ask)
- [x] Return type unchanged: `(dict, int, str)`
- [ ] Backtester run (not yet installed)

**Result**: PASS (manual review). Awaiting backtester PnL check.

**Expected observation after upload**:
- Trades should actually execute (fills occur)
- PnL curve shifts from flat to dynamic

**Failures**: None.

## Run 4 — Reservation Price + 2-Layer Quoting (2026-04-12)

**Method**: Manual code review

**Checks**:
- [x] mid_price computed as (best_bid + best_ask) / 2
- [x] reservation_price = mid_price - ALPHA * position (ALPHA=0.1)
- [x] my_bid / my_ask derived from reservation_price +/- width
- [x] Prices are integers (int cast applied)
- [x] Crossing guard: my_bid >= my_ask -> fallback to best_bid / best_ask
- [x] Empty book (one-sided) -> skip with log, no crash
- [x] Layer 1: 1 lot at my_bid / my_ask
- [x] Layer 2: 1 lot at my_bid-1 / my_ask+1
- [x] Position limits respected for both layers
- [x] Log line includes: best_bid, best_ask, mid, reservation_price, position, my_bid, my_ask, order count
- [x] Return type unchanged: `(dict, int, str)`
- [ ] Backtester run (not yet installed)

**Result**: PASS (manual review). Awaiting backtester PnL check.

**Expected observation after upload**:
- Position should oscillate around zero (inventory control active)
- Quotes shift against inventory: long -> lower prices, short -> higher prices
- 2 layers provide more fill opportunities without excessive risk

**Failures**: None.

## Run 5 — Competitive Quoting + Inventory Skew Fix (2026-04-12)

**Problem**: Run 4 quotes were at or worse than best_bid/best_ask -> zero fills.

**Method**: Manual code review

**Checks**:
- [x] Base quotes inside spread: best_bid+1 / best_ask-1 when spread > 1
- [x] Inventory skew applied on top of base quotes (not replacing them)
- [x] skew = int(ALPHA * position), applied symmetrically to bid and ask
- [x] Crossing guard preserved
- [x] 2-layer structure unchanged
- [x] Position limits respected
- [x] Log line includes spread, base quotes, final quotes
- [x] Return type unchanged: `(dict, int, str)`
- [ ] Backtester run (not yet installed)

**Result**: PASS (manual review). Awaiting backtester PnL check.

**Expected observation after upload**:
- Fills resume (quotes are inside the spread, competitive)
- PnL curve trends upward again
- Position still oscillates around zero via skew

**Failures**: None.
