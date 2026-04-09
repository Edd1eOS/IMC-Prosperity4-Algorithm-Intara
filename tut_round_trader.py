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

            # Buy 1 lot at best ask if sell_orders exist and position allows
            if order_depth.sell_orders:
                best_ask = min(order_depth.sell_orders.keys())
                if position + 1 <= limit:
                    symbol_orders.append(Order(symbol, best_ask, 1))

            # Sell 1 lot at best bid if buy_orders exist and position allows
            if order_depth.buy_orders:
                best_bid = max(order_depth.buy_orders.keys())
                if position - 1 >= -limit:
                    symbol_orders.append(Order(symbol, best_bid, -1))

            if symbol_orders:
                orders[symbol] = symbol_orders

        conversions = 0
        trader_data = ""

        return orders, conversions, trader_data
