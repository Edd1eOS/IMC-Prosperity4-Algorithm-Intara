"""
round2_trader.py — IMC Prosperity 4 Round 2 Strategy [v12.1]
============================================================
Products (position limits +/-80 each):
  ASH_COATED_OSMIUM    — Mean-reverting (FV~10000, spread~16)
  INTARIAN_PEPPER_ROOT — Trending (+0.1/tick drift, ~+100 per 1K ticks)

R2 Environment:
  - Evaluation: 1000 ticks (vs R1's 10000), only Day 1
  - Market Access Fee (MAF): bid() for 25% extra order book quotes
  - Visible quotes: 80% of full book (100% with accepted MAF bid)

v12.1 — Dual-FV Fix (vs v12.0, PnL 8539, OSM 1199):
  Root cause: FV=10000 but market mid~10008 → permanent sell bias → locked at -80
  Fix: split taker and maker FV sources
    Taker FV = microprice (true market center ~10008)
      → sell only when bid > microprice+edge (rare, high-edge trades)
      → buy when ask < microprice-edge (common, catches real dips)
    Maker FV = 10000 + L1_imbalance * 1.5 (long-term anchor)
      → passive quotes still capture mean-reversion premium
    Position unwind uses microprice → actually triggers
    Passive lot cap: 40/side (prevents -80 lockout)
  PPR ENGINE — unchanged
"""

import json
import math
from datamodel import OrderDepth, TradingState, Order

# ================================================================
# Constants
# ================================================================
SYM_OSM = "ASH_COATED_OSMIUM"
SYM_PPR = "INTARIAN_PEPPER_ROOT"
OSM_LIMIT = 80
PPR_LIMIT = 80

# --- OSM Dual-FV Market Making ---
OSM_FAIR         = 10000  # Known fair value anchor (maker FV)
OSM_EDGE         = 1.0    # Min ticks from taker_fv to aggressively take
OSM_IMB_MULT     = 1.5    # L1 imbalance -> maker FV adjustment
OSM_INV_STRENGTH = 4.0    # Inventory skew: (pos/limit) * strength
OSM_PASSIVE_CAP  = 40     # Max passive lot per side (prevent -80 lockout)

# --- PPR Aggressive Build (v8.0 restored) ---
PPR_DRIFT_BIAS   = 10    # v9.1: restored from v8.0 (v9.0's 4 was too slow)
PPR_EMA_ALPHA    = 0.6
PPR_MICRO_WEIGHT = 0.7
PPR_MM_LOT       = 25    # Max maker lot per side

# --- Shared ---
MAX_HISTORY     = 20
MIN_HISTORY     = 3
MAX_LOG_LEN     = 3750
MAX_TRADER_DATA = 3800

TRADING_CONFIG = {
    SYM_OSM: {"limit": OSM_LIMIT},
    SYM_PPR: {"limit": PPR_LIMIT},
}


# ================================================================
# Logger
# ================================================================
class Logger:
    def __init__(self) -> None:
        self._buf:  list[str] = []
        self._used: int       = 0

    def log(self, *args) -> None:
        msg = " ".join(str(a) for a in args)
        cost = len(msg) + 1
        if self._used + cost > MAX_LOG_LEN:
            return
        self._buf.append(msg)
        self._used += cost

    def flush(self) -> None:
        if self._buf:
            print("\n".join(self._buf))
        self._buf.clear()
        self._used = 0


# ================================================================
# Shared Helpers
# ================================================================

def compute_microprice(order_depth: OrderDepth) -> float | None:
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return None
    best_bid = max(order_depth.buy_orders.keys())
    best_ask = min(order_depth.sell_orders.keys())
    q_bid = abs(order_depth.buy_orders[best_bid])
    q_ask = abs(order_depth.sell_orders[best_ask])
    total = q_bid + q_ask
    if total == 0:
        return (best_bid + best_ask) / 2.0
    return (best_bid * q_ask + best_ask * q_bid) / total


def compute_ema(prices: list, alpha: float = PPR_EMA_ALPHA) -> float:
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return ema


# ================================================================
# OSM Engine: Dual-FV Market Making
# ================================================================

def osm_generate_orders(
    od: OrderDepth, pos: int, taker_fv: float, maker_fv: float, logger: Logger,
) -> list[Order]:
    """
    Dual-FV architecture:
      taker_fv = microprice (true market center) → drives taker + unwind
      maker_fv = 10000 + imb (long-term anchor) → drives passive quotes
    Phase 1 — Taker: sweep mispriced vs microprice + unwind inventory
    Phase 2 — Maker: capped passive quotes anchored on 10000
    """
    orders = []
    best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
    best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

    if best_bid is None or best_ask is None:
        return orders

    buy_budget = OSM_LIMIT - pos
    sell_budget = OSM_LIMIT + pos
    buy_used = 0
    sell_used = 0

    # ---- Phase 1: Taker + Position Unwind (using microprice) ----
    for ask_p in sorted(od.sell_orders.keys()):
        if buy_used >= buy_budget:
            break
        if ask_p < taker_fv - OSM_EDGE:
            qty = min(abs(od.sell_orders[ask_p]), buy_budget - buy_used)
            if qty > 0:
                orders.append(Order(SYM_OSM, ask_p, qty))
                buy_used += qty
        elif ask_p <= taker_fv and pos < 0:
            qty = min(abs(od.sell_orders[ask_p]),
                      min(abs(pos) - buy_used, buy_budget - buy_used))
            if qty > 0:
                orders.append(Order(SYM_OSM, ask_p, qty))
                buy_used += qty

    for bid_p in sorted(od.buy_orders.keys(), reverse=True):
        if sell_used >= sell_budget:
            break
        if bid_p > taker_fv + OSM_EDGE:
            qty = min(od.buy_orders[bid_p], sell_budget - sell_used)
            if qty > 0:
                orders.append(Order(SYM_OSM, bid_p, -qty))
                sell_used += qty
        elif bid_p >= taker_fv and pos > 0:
            qty = min(od.buy_orders[bid_p],
                      min(pos - sell_used, sell_budget - sell_used))
            if qty > 0:
                orders.append(Order(SYM_OSM, bid_p, -qty))
                sell_used += qty

    # ---- Phase 2: Capped Passive Maker (using 10000 anchor) ----
    inv_skew = (pos / OSM_LIMIT) * OSM_INV_STRENGTH
    adj_fair = maker_fv - inv_skew

    bid_wall = min(od.buy_orders) if od.buy_orders else None
    ask_wall = max(od.sell_orders) if od.sell_orders else None

    bid_px = int(bid_wall + 1) if bid_wall is not None else int(adj_fair - 8)
    if best_bid is not None:
        candidate = best_bid + 1
        if candidate < adj_fair:
            bid_px = max(bid_px, candidate)
        elif best_bid < adj_fair:
            bid_px = max(bid_px, best_bid)

    ask_px = int(ask_wall - 1) if ask_wall is not None else int(adj_fair + 8)
    if best_ask is not None:
        candidate = best_ask - 1
        if candidate > adj_fair:
            ask_px = min(ask_px, candidate)
        elif best_ask > adj_fair:
            ask_px = min(ask_px, best_ask)

    if bid_px >= ask_px:
        bid_px = int(round(maker_fv)) - 1
        ask_px = int(round(maker_fv)) + 1

    buy_room = min(buy_budget - buy_used, OSM_PASSIVE_CAP)
    if buy_room > 0:
        orders.append(Order(SYM_OSM, bid_px, buy_room))

    sell_room = min(sell_budget - sell_used, OSM_PASSIVE_CAP)
    if sell_room > 0:
        orders.append(Order(SYM_OSM, ask_px, -sell_room))

    return orders


# ================================================================
# PPR Engine: Aggressive Build (v8.0 logic restored)
# ================================================================

def ppr_generate_orders(
    od: OrderDepth, pos: int, fv: float, logger: Logger,
) -> list[Order]:
    """
    Aggressive position building for known-drift asset. Never sell.
    Phase 1 — Taker: sweep ALL ask levels below FV (full book)
    Phase 2 — Maker: bid at FV - 1, clamped to book bounds
    """
    orders = []
    best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
    best_bid = max(od.buy_orders.keys()) if od.buy_orders else None

    sim_pos = pos
    fv_int = round(fv)

    # ---- Phase 1: Full-book Taker (v8.0 restored) ----
    # Sweep ALL ask levels below FV, no position penalty (taker_alpha=0)
    for ask_p in sorted(od.sell_orders.keys()):
        if ask_p >= fv_int:
            break
        remaining = PPR_LIMIT - sim_pos
        if remaining <= 0:
            break
        vol = min(abs(od.sell_orders[ask_p]), remaining)
        if vol > 0:
            orders.append(Order(SYM_PPR, ask_p, vol))
            sim_pos += vol

    # ---- Phase 2: Maker Bid ----
    remaining = PPR_LIMIT - sim_pos
    if remaining > 0:
        bid_price = fv_int - 1
        if best_ask is not None:
            bid_price = min(bid_price, best_ask - 1)
        if best_bid is not None:
            bid_price = max(bid_price, best_bid)

        lot = min(remaining, PPR_MM_LOT)
        if lot > 0:
            orders.append(Order(SYM_PPR, bid_price, lot))

    return orders


# ================================================================
# Trader
# ================================================================

class Trader:

    def bid(self) -> int:
        return 0

    def run(self, state: TradingState) -> tuple:
        logger = Logger()
        result: dict[str, list] = {}

        # ============================================================
        # Module 1: State Deserialization
        # ============================================================
        try:
            memory = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            memory = {}

        ppr_history: list        = memory.get("ppr_history", [])

        # ============================================================
        # Module 2: ASH_COATED_OSMIUM — Dual-FV MM
        # ============================================================
        try:
            if SYM_OSM in state.order_depths:
                od_osm  = state.order_depths[SYM_OSM]
                pos_osm = state.position.get(SYM_OSM, 0)

                best_bid_osm = max(od_osm.buy_orders.keys()) if od_osm.buy_orders else None
                best_ask_osm = min(od_osm.sell_orders.keys()) if od_osm.sell_orders else None

                # Taker FV = microprice (true market center)
                taker_fv = compute_microprice(od_osm)
                if taker_fv is None and best_bid_osm is not None and best_ask_osm is not None:
                    taker_fv = (best_bid_osm + best_ask_osm) / 2.0
                if taker_fv is None:
                    taker_fv = float(OSM_FAIR)

                # Maker FV = 10000 + L1 imbalance (long-term anchor)
                maker_fv = float(OSM_FAIR)
                if best_bid_osm is not None and best_ask_osm is not None:
                    bid_vol = abs(od_osm.buy_orders.get(best_bid_osm, 0))
                    ask_vol = abs(od_osm.sell_orders.get(best_ask_osm, 0))
                    total_vol = bid_vol + ask_vol
                    if total_vol > 0:
                        maker_fv += ((bid_vol - ask_vol) / total_vol) * OSM_IMB_MULT

                osm_orders = osm_generate_orders(od_osm, pos_osm, taker_fv, maker_fv, logger)
                if osm_orders:
                    result[SYM_OSM] = osm_orders
        except Exception as e:
            logger.log(f"[OSM ERR] {e}")

        # ============================================================
        # Module 3: INTARIAN_PEPPER_ROOT — Smart Build
        # ============================================================
        try:
            if SYM_PPR in state.order_depths:
                od_ppr  = state.order_depths[SYM_PPR]
                pos_ppr = state.position.get(SYM_PPR, 0)

                micro = compute_microprice(od_ppr)
                if micro is None and od_ppr.buy_orders and od_ppr.sell_orders:
                    micro = (max(od_ppr.buy_orders) + min(od_ppr.sell_orders)) / 2.0

                if micro is not None:
                    ppr_history.append(micro)
                    if len(ppr_history) > MAX_HISTORY:
                        ppr_history = ppr_history[-MAX_HISTORY:]

                # FV: weighted blend of EMA + microprice + drift bias
                if micro is not None and len(ppr_history) >= MIN_HISTORY:
                    ema = compute_ema(ppr_history)
                    ppr_fv = (1.0 - PPR_MICRO_WEIGHT) * ema + PPR_MICRO_WEIGHT * micro + PPR_DRIFT_BIAS
                elif micro is not None:
                    ppr_fv = micro + PPR_DRIFT_BIAS
                else:
                    ppr_fv = None

                if ppr_fv is not None:
                    ppr_orders = ppr_generate_orders(od_ppr, pos_ppr, ppr_fv, logger)
                    if ppr_orders:
                        result[SYM_PPR] = ppr_orders
        except Exception as e:
            logger.log(f"[PPR ERR] {e}")

        # ============================================================
        # Module 4: Position Clamping (safety net)
        # ============================================================
        for sym, orders_list in result.items():
            limit = TRADING_CONFIG.get(sym, {}).get("limit", 80)
            sim   = state.position.get(sym, 0)
            clamped = []
            for order in orders_list:
                if order.quantity > 0:
                    max_buy = limit - sim
                    vol = min(order.quantity, max_buy)
                    if vol < order.quantity:
                        logger.log(f"[CLAMP BUY] {sym} {order.quantity}->{vol} @{order.price} pos={sim}")
                    if vol > 0:
                        clamped.append(Order(sym, order.price, vol))
                        sim += vol
                elif order.quantity < 0:
                    max_sell = limit + sim
                    vol = min(abs(order.quantity), max_sell)
                    if vol < abs(order.quantity):
                        logger.log(f"[CLAMP SELL] {sym} {order.quantity}->-{vol} @{order.price} pos={sim}")
                    if vol > 0:
                        clamped.append(Order(sym, order.price, -vol))
                        sim -= vol
            result[sym] = clamped

        # ============================================================
        # State Serialization
        # ============================================================
        memory["ppr_history"] = ppr_history
        trader_data = json.dumps(memory)

        if len(trader_data) > MAX_TRADER_DATA:
            memory["ppr_history"] = memory["ppr_history"][-5:]
            trader_data = json.dumps(memory)
            logger.log(f"[STATE TRIM] len={len(trader_data)}")

        logger.flush()
        return result, 0, trader_data
