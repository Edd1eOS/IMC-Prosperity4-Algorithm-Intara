from datamodel import OrderDepth, TradingState, Order, Symbol, Trade, ProsperityEncoder

# Unified per-asset configuration dictionary
# limit: position hard cap (absolute value)
# alpha: inventory skew coefficient
# base_spread: reserved for future spread-width logic
TRADING_CONFIG = {
    "AMETHYSTS": {"limit": 20, "alpha": 0.05, "base_spread": 2},
    "STARFISH":  {"limit": 20, "alpha": 0.5,  "base_spread": 4},
    "EMERALDS":  {"limit": 80, "alpha": 0.1,  "base_spread": 1},
    "TOMATOES":  {"limit": 80, "alpha": 0.1,  "base_spread": 1},
}


def clamp_order_volume(symbol: str, desired_vol: int, position: int, limit: int) -> int:
    """Hard-clamp order volume so that position never exceeds [-limit, +limit].
    Returns clamped volume. Returns 0 if order should be dropped entirely."""
    if desired_vol > 0:
        max_buy = limit - position
        actual = min(desired_vol, max_buy)
        if actual <= 0:
            print(f"{symbol} | CLAMP DROP BUY: desired={desired_vol} actual=0 pos={position} limit={limit}")
            return 0
        if actual != desired_vol:
            print(f"{symbol} | CLAMP BUY: desired={desired_vol} actual={actual} pos={position} limit={limit}")
        return actual
    elif desired_vol < 0:
        max_sell = -limit - position
        actual = max(desired_vol, max_sell)
        if actual >= 0:
            print(f"{symbol} | CLAMP DROP SELL: desired={desired_vol} actual=0 pos={position} limit={limit}")
            return 0
        if actual != desired_vol:
            print(f"{symbol} | CLAMP SELL: desired={desired_vol} actual={actual} pos={position} limit={limit}")
        return actual
    return 0


class Trader:

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        orders: dict[Symbol, list[Order]] = {}

        for symbol, order_depth in state.order_depths.items():
            symbol_orders: list[Order] = []
            position = state.position.get(symbol, 0)

            cfg = TRADING_CONFIG.get(symbol)
            if cfg is None:
                print(f"{symbol} | SKIP (no config) | pos={position}")
                continue
            limit = cfg["limit"]
            alpha = cfg["alpha"]

            best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
            best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

            if best_bid is None or best_ask is None:
                print(f"{symbol} | SKIP (no two-sided book) | pos={position}")
                continue

            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

            # Step 1: Competitive base quotes — get inside the spread for queue priority
            if spread > 1:
                base_bid = best_bid + 1
                base_ask = best_ask - 1
            else:
                base_bid = best_bid
                base_ask = best_ask

            # Step 2: Inventory skew — shift quotes against position to mean-revert
            reservation_price = mid_price - alpha * position
            skew = int(alpha * position)

            my_bid = base_bid - skew
            my_ask = base_ask - skew

            # Safety: ensure no crossing; fallback to raw market prices
            if my_bid >= my_ask:
                my_bid = best_bid
                my_ask = best_ask

            # Layer 1 (aggressive): 1 lot at tighter price
            vol = clamp_order_volume(symbol, 1, position, limit)
            if vol > 0:
                symbol_orders.append(Order(symbol, my_bid, vol))
            vol = clamp_order_volume(symbol, -1, position, limit)
            if vol < 0:
                symbol_orders.append(Order(symbol, my_ask, vol))

            # Layer 2 (passive): 1 lot at wider price
            pending_buy = sum(o.quantity for o in symbol_orders if o.quantity > 0)
            pending_sell = sum(o.quantity for o in symbol_orders if o.quantity < 0)
            vol = clamp_order_volume(symbol, 1, position + pending_buy, limit)
            if vol > 0:
                symbol_orders.append(Order(symbol, my_bid - 1, vol))
            vol = clamp_order_volume(symbol, -1, position + pending_sell, limit)
            if vol < 0:
                symbol_orders.append(Order(symbol, my_ask + 1, vol))

            if symbol_orders:
                orders[symbol] = symbol_orders

            print(
                f"{symbol} | bid={best_bid} ask={best_ask} spread={spread} pos={position} "
                f"base={base_bid}/{base_ask} my={my_bid}/{my_ask} orders={len(symbol_orders)}"
            )

        conversions = 0
        trader_data = ""

        return orders, conversions, trader_data
