from datamodel import OrderDepth, TradingState, Order, Symbol, Trade, ProsperityEncoder

POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 80,
}

# Inventory penalty coefficient: higher alpha = stronger mean-reversion toward zero position
ALPHA = 0.1


class Trader:

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        orders: dict[Symbol, list[Order]] = {}

        for symbol, order_depth in state.order_depths.items():
            symbol_orders: list[Order] = []
            position = state.position.get(symbol, 0)
            limit = POSITION_LIMITS.get(symbol, 0)

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
            # reservation_price used as directional signal only
            reservation_price = mid_price - ALPHA * position
            skew = int(ALPHA * position)

            my_bid = base_bid - skew
            my_ask = base_ask - skew

            # Safety: ensure no crossing; fallback to raw market prices
            if my_bid >= my_ask:
                my_bid = best_bid
                my_ask = best_ask

            # Layer 1 (aggressive): 1 lot at tighter price
            if position + 1 <= limit:
                symbol_orders.append(Order(symbol, my_bid, 1))
            if position - 1 >= -limit:
                symbol_orders.append(Order(symbol, my_ask, -1))

            # Layer 2 (passive): 1 lot at wider price
            if position + 2 <= limit:
                symbol_orders.append(Order(symbol, my_bid - 1, 1))
            if position - 2 >= -limit:
                symbol_orders.append(Order(symbol, my_ask + 1, -1))

            if symbol_orders:
                orders[symbol] = symbol_orders

            print(
                f"{symbol} | bid={best_bid} ask={best_ask} spread={spread} pos={position} "
                f"base={base_bid}/{base_ask} my={my_bid}/{my_ask} orders={len(symbol_orders)}"
            )

        conversions = 0
        trader_data = ""

        return orders, conversions, trader_data
