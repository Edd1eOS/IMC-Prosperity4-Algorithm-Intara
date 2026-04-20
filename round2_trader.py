"""
round2_trader.py — IMC Prosperity 4 Round 2 Strategy [v9.1]
============================================================
Products (position limits +/-80 each):
  ASH_COATED_OSMIUM    — Mean-reverting (FV~10000, spread~16)
  INTARIAN_PEPPER_ROOT — Trending (+0.1/tick drift, ~+100 per 1K ticks)

R2 Environment:
  - Evaluation: 1000 ticks (vs R1's 10000), only Day 1
  - Market Access Fee (MAF): bid() for 25% extra order book quotes
  - Visible quotes: 80% of full book (100% with accepted MAF bid)

v9.1 Hotfix (vs v9.0, PnL 7665->target ~9100):
  PPR regression fix: restore v8.0 aggressive full-book sweep (DRIFT_BIAS=10)
  v9.0 L1-only + DRIFT_BIAS=4 caused 333-tick fill delay -> -1427 PPR PnL
  OSM penny-jump retained (v9.0 OSM PnL 1105 vs v8.0 223, +882)

Retained from v9.0:
  1. bid() = 1000 (MAF game theory)
  2. OSM Penny-Jump MM (best_bid+1 / best_ask-1, linear inventory skew)
  3. Kalman warm-start from first microprice (P0=5)
Reverted to v8.0:
  4. PPR full-book taker sweep (DRIFT_BIAS=10, no L1 restriction)
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

# --- OSM Kalman Filter ---
OSM_KALMAN_Q  = 0.02     # v9.0: 0.015->0.02 (slightly faster adaptation)
OSM_KALMAN_R  = 4.0
OSM_KALMAN_P0 = 5.0      # v9.0: 25->5 (warm-start, lower initial uncertainty)

# --- OSM Penny-Jump Market Making ---
OSM_TAKER_ALPHA = 0.1    # Position-aware taker threshold coefficient
OSM_MM_LOT      = 25     # v9.0: 20->25 (max maker lot per side)
OSM_INV_SKEW    = 0.08   # Ticks of skew per unit of position
OSM_FV_SKEW     = 0.3    # FV deviation signal weight
OSM_CUTOFF_POS  = 60     # Don't add to losing side beyond this position

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


def compute_obi(order_depth: OrderDepth) -> float:
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return 0.0
    v_bid = sum(abs(v) for v in order_depth.buy_orders.values())
    v_ask = sum(abs(v) for v in order_depth.sell_orders.values())
    total = v_bid + v_ask
    if total == 0:
        return 0.0
    return (v_bid - v_ask) / total


def kalman_update_1d(
    x: float, P: float, z: float,
    Q: float = OSM_KALMAN_Q,
    R: float = OSM_KALMAN_R,
) -> tuple[float, float]:
    P_pred = P + Q
    K      = P_pred / (P_pred + R)
    x_new  = x + K * (z - x)
    P_new  = (1.0 - K) * P_pred
    return x_new, P_new


def compute_ema(prices: list, alpha: float = PPR_EMA_ALPHA) -> float:
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return ema


# ================================================================
# OSM Engine: Penny-Jump Market Making
# ================================================================

def osm_generate_orders(
    od: OrderDepth, pos: int, fv: float, logger: Logger,
) -> list[Order]:
    """
    Phase 1 — Taker: buy mispriced asks / sell mispriced bids (position-aware)
    Phase 2 — Maker: penny-jump inside the spread, skewed by inventory + FV signal
    """
    orders = []
    best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
    best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

    if best_bid is None or best_ask is None:
        return orders

    fv_int = round(fv)
    sim_pos = pos

    # ---- Phase 1: Taker ----
    for ask_p in sorted(od.sell_orders.keys()):
        thr = fv_int - round(OSM_TAKER_ALPHA * max(sim_pos, 0))
        if ask_p >= thr:
            break
        vol = min(abs(od.sell_orders[ask_p]), OSM_LIMIT - sim_pos)
        if vol <= 0:
            break
        orders.append(Order(SYM_OSM, ask_p, vol))
        sim_pos += vol

    for bid_p in sorted(od.buy_orders.keys(), reverse=True):
        thr = fv_int + round(OSM_TAKER_ALPHA * max(-sim_pos, 0))
        if bid_p <= thr:
            break
        vol = min(od.buy_orders[bid_p], OSM_LIMIT + sim_pos)
        if vol <= 0:
            break
        orders.append(Order(SYM_OSM, bid_p, -vol))
        sim_pos -= vol

    # ---- Phase 2: Penny-Jump Maker ----
    spread = best_ask - best_bid
    if spread < 2:
        return orders

    if spread >= 4:
        base_bid = best_bid + 1
        base_ask = best_ask - 1
    else:
        base_bid = best_bid
        base_ask = best_ask

    # Inventory gradient skew: shift both quotes to reduce position
    # pos > 0 (long) -> lower both prices -> sell cheaper, bid less
    # pos < 0 (short) -> raise both prices -> buy more, ask higher
    inv_skew = round(OSM_INV_SKEW * sim_pos)

    # FV signal: if Kalman FV deviates from mid, shift quotes
    mid = (best_bid + best_ask) / 2.0
    fv_shift = round(OSM_FV_SKEW * (fv - mid))

    my_bid = base_bid - inv_skew + fv_shift
    my_ask = base_ask - inv_skew + fv_shift

    # Non-crossing safety
    my_bid = min(my_bid, best_ask - 1)
    my_ask = max(my_ask, best_bid + 1)
    if my_bid >= my_ask:
        my_bid = round(mid) - 1
        my_ask = round(mid) + 1

    # Capacity — cut off at extreme inventory
    buy_cap  = min(OSM_LIMIT - sim_pos, OSM_MM_LOT)
    sell_cap = min(OSM_LIMIT + sim_pos, OSM_MM_LOT)
    if sim_pos > OSM_CUTOFF_POS:
        buy_cap = 0
    if sim_pos < -OSM_CUTOFF_POS:
        sell_cap = 0

    if buy_cap > 0:
        orders.append(Order(SYM_OSM, my_bid, buy_cap))
    if sell_cap > 0:
        orders.append(Order(SYM_OSM, my_ask, -sell_cap))

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
        return 1000

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
        osm_history: list        = memory.get("osm_history", [])
        osm_kf_x: float | None  = memory.get("osm_kf_x", None)
        osm_kf_P: float         = memory.get("osm_kf_P", OSM_KALMAN_P0)

        # ============================================================
        # Module 2: ASH_COATED_OSMIUM — Penny-Jump MM
        # ============================================================
        try:
            if SYM_OSM in state.order_depths:
                od_osm  = state.order_depths[SYM_OSM]
                pos_osm = state.position.get(SYM_OSM, 0)

                micro_osm = compute_microprice(od_osm)
                if micro_osm is None and od_osm.buy_orders and od_osm.sell_orders:
                    micro_osm = (max(od_osm.buy_orders) + min(od_osm.sell_orders)) / 2.0

                if micro_osm is not None:
                    osm_history.append(micro_osm)
                    if len(osm_history) > MAX_HISTORY:
                        osm_history = osm_history[-MAX_HISTORY:]

                # Kalman warm-start: initialize from first observation
                if osm_kf_x is None:
                    osm_kf_x = micro_osm if micro_osm is not None else 10000.0
                    osm_kf_P = OSM_KALMAN_P0

                if micro_osm is not None:
                    osm_kf_x, osm_kf_P = kalman_update_1d(
                        osm_kf_x, osm_kf_P, micro_osm,
                        Q=OSM_KALMAN_Q, R=OSM_KALMAN_R,
                    )

                osm_orders = osm_generate_orders(od_osm, pos_osm, osm_kf_x, logger)
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
        memory["osm_history"] = osm_history
        memory["osm_kf_x"]   = osm_kf_x
        memory["osm_kf_P"]   = osm_kf_P
        trader_data = json.dumps(memory)

        if len(trader_data) > MAX_TRADER_DATA:
            memory["ppr_history"] = memory["ppr_history"][-5:]
            memory["osm_history"] = memory["osm_history"][-5:]
            trader_data = json.dumps(memory)
            logger.log(f"[STATE TRIM] len={len(trader_data)}")

        logger.flush()
        return result, 0, trader_data
