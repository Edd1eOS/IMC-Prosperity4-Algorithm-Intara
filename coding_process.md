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
