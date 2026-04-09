from datamodel import OrderDepth, TradingState, Order, Symbol, Trade, ProsperityEncoder

POSITION_LIMITS = {
    "EMERALDS": 80,
    "TOMATOES": 80,
}


class Trader:

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        orders: dict[Symbol, list[Order]] = {}

        for symbol, order_depth in state.order_depths.items():
            symbol_orders: list[Order] = []
            position = state.position.get(symbol, 0)
            limit = POSITION_LIMITS.get(symbol, 0)

            best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
            best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

            spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None

            # Competitive pricing: post inside the spread when possible
            if spread is not None and spread > 1:
                my_bid = best_bid + 1
                my_ask = best_ask - 1
            else:
                my_bid = best_bid
                my_ask = best_ask

            # Safety: ensure no crossing
            if my_bid is not None and my_ask is not None and my_bid >= my_ask:
                my_bid = best_bid
                my_ask = best_ask

            if my_bid is not None and position + 1 <= limit:
                symbol_orders.append(Order(symbol, my_bid, 1))

            if my_ask is not None and position - 1 >= -limit:
                symbol_orders.append(Order(symbol, my_ask, -1))

            if symbol_orders:
                orders[symbol] = symbol_orders

            print(f"{symbol} | bid={best_bid} | ask={best_ask} | spread={spread} | my_bid={my_bid} | my_ask={my_ask} | pos={position} | orders={len(symbol_orders)}")

        conversions = 0
        trader_data = ""

        return orders, conversions, trader_data
