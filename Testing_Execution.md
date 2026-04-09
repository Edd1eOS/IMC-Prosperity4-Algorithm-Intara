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
