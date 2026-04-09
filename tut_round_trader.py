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

            # Post buy order at best bid (provide liquidity on bid side)
            if best_bid is not None and position + 1 <= limit:
                symbol_orders.append(Order(symbol, best_bid, 1))

            # Post sell order at best ask (provide liquidity on ask side)
            if best_ask is not None and position - 1 >= -limit:
                symbol_orders.append(Order(symbol, best_ask, -1))

            if symbol_orders:
                orders[symbol] = symbol_orders

            spread = (best_ask - best_bid) if (best_bid is not None and best_ask is not None) else None
            print(f"{symbol}|bid={best_bid}|ask={best_ask}|spread={spread}|pos={position}|orders={len(symbol_orders)}")

        conversions = 0
        trader_data = ""

        return orders, conversions, trader_data
