# Testing Guide

## Phase Test (per phase)

Run the backtester against tutorial round data:

```sh
prosperity4btx tut_round_trader.py 0
```

**Pass criteria**:
- No exceptions or tracebacks
- PnL output is displayed (value does not matter in skeleton phase)
- No "exceeded limit" warnings in sandbox log

## Smoke Test (after every change)

1. **Return type**: `run()` returns `(dict[Symbol, list[Order]], int, str)`
2. **No crash on empty book**: if a product has no bids or asks, no KeyError
3. **Import correctness**: only `from datamodel import ...` (platform-provided)

## Current Phase: Skeleton

Testing method: manual code review against platform contract.
Backtester not yet installed — will be added in a future phase.
