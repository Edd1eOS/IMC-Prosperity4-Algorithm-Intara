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
