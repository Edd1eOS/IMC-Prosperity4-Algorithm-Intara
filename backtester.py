"""
backtester.py - IMC Prosperity 4 Local Backtester v1

Naive matching engine with mark-to-market PnL tracking.
Usage: python backtester.py <path_to_csv>
"""
# ================================================================
# CHANGELOG v5.4
# - FILL_PROB_IMPROVEMENT: 0.3 → 0.03  (compress local PnL to ~3k-5k)
# - FILL_PROB_QUEUE:       0.1 → 0.02
# - MTM forward-fill: last_valid_mid prevents pos*0 spike when mid_price missing
# ================================================================

import sys
import os
from types import ModuleType
from collections import defaultdict


# ================================================================
# Part 0: 平台数据模型桩 (Platform Datamodel Stubs)
# ================================================================
# tut_round_trader.py 从 'datamodel' 导入类型定义，该模块仅存在于
# IMC 云端沙盒中。此处定义签名兼容的桩类，并在 Trader 导入前
# 注入 sys.modules，实现零修改本地调用。


class Order:
    def __init__(self, symbol: str, price: int, quantity: int):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

    def __repr__(self):
        return f"Order({self.symbol}, {self.price}, {self.quantity})"


class OrderDepth:
    def __init__(self):
        self.buy_orders: dict[int, int] = {}   # price -> volume (正数)
        self.sell_orders: dict[int, int] = {}  # price -> volume (负数, IMC 平台惯例)


class TradingState:
    def __init__(self, timestamp, listings, order_depths, own_trades,
                 market_trades, position, observations, traderData):
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations
        self.traderData = traderData


class Trade:
    def __init__(self, symbol="", price=0, quantity=0,
                 buyer="", seller="", timestamp=0):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp


class ProsperityEncoder:
    pass


Symbol = str

# 将桩类注入 sys.modules["datamodel"]，使 tut_round_trader.py 的
# "from datamodel import ..." 语句可以正常执行
_dm = ModuleType("datamodel")
for _n, _o in [("Order", Order), ("OrderDepth", OrderDepth),
               ("TradingState", TradingState), ("Trade", Trade),
               ("ProsperityEncoder", ProsperityEncoder), ("Symbol", Symbol)]:
    setattr(_dm, _n, _o)
sys.modules["datamodel"] = _dm

# -- 桩注入完成，安全导入 Trader --
from round1_trader import Trader, TRADING_CONFIG

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # non-interactive backend: save to file instead of blocking popup
import matplotlib.pyplot as plt


# ================================================================
# Part 1: 数据加载 (Data Loading)
# ================================================================

def load_csv(filepath: str) -> pd.DataFrame:
    """
    读取官方 CSV 数据文件。
    自动检测分隔符: 先尝试分号(;)，若列数 <= 1 则回退到逗号(,)。
    返回列名已去空格的 DataFrame。
    """
    df = pd.read_csv(filepath, sep=";")
    if len(df.columns) <= 1:
        df = pd.read_csv(filepath, sep=",")
    df.columns = df.columns.str.strip()
    print(f"[DATA] {filepath}: {len(df)} rows, columns={list(df.columns)}")
    return df


# ================================================================
# Part 2: 状态组装 (State Building)
# ================================================================

def build_order_depth(row: pd.Series, columns: list[str]) -> OrderDepth:
    """
    从 CSV 单行构建 OrderDepth 对象。

    买方 (buy_orders):  price -> volume (正数)
    卖方 (sell_orders): price -> volume (负数, 符合 IMC 平台惯例)
    支持最多 3 层报价深度。
    """
    od = OrderDepth()

    # 构建买方订单簿
    for level in [1, 2, 3]:
        bp_col, bv_col = f"bid_price_{level}", f"bid_volume_{level}"
        if bp_col in columns and bv_col in columns:
            bp, bv = row.get(bp_col), row.get(bv_col)
            if pd.notna(bp) and pd.notna(bv) and int(float(bv)) != 0:
                od.buy_orders[int(float(bp))] = abs(int(float(bv)))

    # 构建卖方订单簿 (volume 存为负数)
    for level in [1, 2, 3]:
        ap_col, av_col = f"ask_price_{level}", f"ask_volume_{level}"
        if ap_col in columns and av_col in columns:
            ap, av = row.get(ap_col), row.get(av_col)
            if pd.notna(ap) and pd.notna(av) and int(float(av)) != 0:
                od.sell_orders[int(float(ap))] = -abs(int(float(av)))

    return od


def build_state_for_tick(tick_df: pd.DataFrame, positions: dict,
                         trader_data: str, timestamp: int) -> tuple:
    """
    组装单个 tick 的 TradingState 及撮合所需的市场快照。

    返回:
        state        - TradingState 对象（传给 Trader.run()）
        mid_prices   - {product: mid_price}（盯市估值用）
        market_bids  - {product: best_bid_price}（撮合判定用）
        market_asks  - {product: best_ask_price}（撮合判定用）
    """
    order_depths = {}
    mid_prices = {}
    market_bids = {}
    market_asks = {}
    columns = list(tick_df.columns)

    for _, row in tick_df.iterrows():
        product = str(row["product"]).strip()
        od = build_order_depth(row, columns)
        order_depths[product] = od

        # 中间价: 优先取 CSV 中的 mid_price 字段，否则从 best_bid/best_ask 计算
        if "mid_price" in columns and pd.notna(row.get("mid_price")):
            mid_prices[product] = float(row["mid_price"])
        elif od.buy_orders and od.sell_orders:
            mid_prices[product] = (max(od.buy_orders) + min(od.sell_orders)) / 2.0

        # 记录市场最优报价，供撮合引擎判断成交
        if od.buy_orders:
            market_bids[product] = max(od.buy_orders.keys())
        if od.sell_orders:
            market_asks[product] = min(od.sell_orders.keys())

    state = TradingState(
        timestamp=timestamp,
        listings={},
        order_depths=order_depths,
        own_trades={},
        market_trades={},
        position=dict(positions),  # 传副本，防止 Trader 意外修改
        observations=None,
        traderData=trader_data,
    )

    return state, mid_prices, market_bids, market_asks


# ================================================================
# Part 3: 撮合引擎 (Matching Engine - V3 Stochastic Fills)
# ================================================================

# Fill probability parameters (tunable)
FILL_PROB_IMPROVEMENT = 0.03  # v5.4: 0.3→0.03; aligns local PnL to cloud (~3k-5k)
FILL_PROB_QUEUE       = 0.02  # v5.4: 0.1→0.02

def match_orders(orders: dict, market_bids: dict, market_asks: dict,
                 positions: dict, cash: dict) -> list[tuple]:
    """
    V3 随机撮合引擎: 在 V2 价格优先级基础上引入独立随机数，
    打破双边完美成交的平衡，模拟真实散户订单流。

    ┌─────────────────────────────────────────────────────────────┐
    │ 买单 (quantity > 0):                                        │
    │                                                             │
    │ 1. Taker:  order.price >= best_ask                          │
    │    -> 100% 成交，成交价 = best_ask                          │
    │                                                             │
    │ 2. Price Improvement: order.price > best_bid (在 spread 内) │
    │    -> 掷骰子 p < 0.3 才成交，100% 满额，成交价 = order      │
    │                                                             │
    │ 3. Queue Match: order.price == best_bid                     │
    │    -> 掷骰子 p < 0.1 才成交，50% ceil 量，成交价 = order    │
    │                                                             │
    │ 4. Out of Market: order.price < best_bid -> 0               │
    ├─────────────────────────────────────────────────────────────┤
    │ 卖单 (quantity < 0): 完全对称，使用独立的 random.random()   │
    │                                                             │
    │ 1. Taker:  order.price <= best_bid -> 100% @ best_bid       │
    │ 2. Improvement: order.price < best_ask -> p < 0.3, 100%    │
    │ 3. Queue:  order.price == best_ask -> p < 0.1, 50% ceil    │
    │ 4. Out of Market: order.price > best_ask -> 0               │
    ├─────────────────────────────────────────────────────────────┤
    │ 关键设计: 买单和卖单各自独立掷骰子，不会总是同时成交，      │
    │ 产生单边库存累积，触发 inventory skew 机制。                │
    ├─────────────────────────────────────────────────────────────┤
    │ 算账公式:                                                   │
    │   position[product] += fill_qty                             │
    │   cash[product]     -= fill_price * fill_qty                │
    └─────────────────────────────────────────────────────────────┘
    """
    import math
    import random
    fills = []

    for product, order_list in orders.items():
        best_bid = market_bids.get(product)
        best_ask = market_asks.get(product)

        for order in order_list:
            fill_qty = 0
            fill_price = order.price

            if order.quantity > 0:
                # ---- 买单判定 ----
                if best_ask is not None and order.price >= best_ask:
                    # Taker: 穿越 ask，确定性 100% 成交
                    fill_qty = order.quantity
                    fill_price = best_ask
                elif best_bid is not None and order.price > best_bid:
                    # Price Improvement: 30% 概率被散户市价卖单命中
                    if random.random() < FILL_PROB_IMPROVEMENT:
                        fill_qty = order.quantity
                elif best_bid is not None and order.price == best_bid:
                    # Queue Match: 10% 概率排到，50% 量成交
                    if random.random() < FILL_PROB_QUEUE:
                        fill_qty = math.ceil(order.quantity * 0.5)
                # else: Out of Market, 0 成交

            elif order.quantity < 0:
                # ---- 卖单判定 (独立掷骰子) ----
                if best_bid is not None and order.price <= best_bid:
                    # Taker: 穿越 bid，确定性 100% 成交
                    fill_qty = order.quantity
                    fill_price = best_bid
                elif best_ask is not None and order.price < best_ask:
                    # Price Improvement: 30% 概率被散户市价买单命中
                    if random.random() < FILL_PROB_IMPROVEMENT:
                        fill_qty = order.quantity
                elif best_ask is not None and order.price == best_ask:
                    # Queue Match: 10% 概率排到，50% 量成交
                    if random.random() < FILL_PROB_QUEUE:
                        fill_qty = -math.ceil(abs(order.quantity) * 0.5)
                # else: Out of Market, 0 成交

            if fill_qty != 0:
                positions[product] += fill_qty
                cash[product] -= fill_price * fill_qty
                fills.append((product, fill_price, fill_qty))

    return fills


# ================================================================
# Part 4: 盯市估值 (Mark-to-Market PnL)
# ================================================================

def calc_mtm_pnl(cash: dict, positions: dict, mid_prices: dict) -> float:
    """
    计算当前 tick 的盯市盈亏 (Mark-to-Market PnL)。

    公式: PnL = Sigma{ cash[p] + position[p] * mid_price[p] }

    含义: 如果此刻以中间价全部平仓，你能实现的总利润。
    - cash[p]: 该产品所有历史成交的累计现金流（买入扣钱，卖出收钱）
    - position[p] * mid_price[p]: 未平仓持仓按当前市场中间价的估值
    """
    total = 0.0
    for product in set(list(cash.keys()) + list(positions.keys())):
        pos = positions.get(product, 0)
        mid = mid_prices.get(product, 0.0)
        total += cash.get(product, 0.0) + pos * mid
    return total


# ================================================================
# Part 5: 可视化报告 (Visualization)
# ================================================================

def plot_results(results: list[dict], positions_history: list[dict],
                 filepath: str, output_dir: str = "."):
    """
    绘制回测结果图:
    - 上图: PnL 随 tick 变化的曲线 (Mark-to-Market)
    - 下图: 各产品仓位随 tick 变化的阶梯图 + 红色虚线标注仓位上下限
    """
    ticks = [r["tick"] for r in results]
    pnls = [r["pnl"] for r in results]

    # 收集所有出现过的产品名
    all_products = set()
    for ph in positions_history:
        all_products.update(ph.keys())
    all_products = sorted(all_products)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    # -- 上图: PnL 曲线 --
    ax1.plot(ticks, pnls, linewidth=1.0, color="steelblue")
    ax1.set_ylabel("Mark-to-Market PnL")
    ax1.set_title("Local Backtest Results")
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)

    # -- 下图: 仓位曲线 + Limit 边界线 --
    limit_lines_drawn = set()
    for product in all_products:
        series = [ph.get(product, 0) for ph in positions_history]
        ax2.step(ticks, series, where="post", linewidth=1.0, label=product)

        # 为每个不同的 limit 值画一对红色虚线
        cfg = TRADING_CONFIG.get(product)
        if cfg:
            limit = cfg["limit"]
            if limit not in limit_lines_drawn:
                ax2.axhline(y=limit, color="red", linestyle="--",
                            linewidth=0.8, alpha=0.6, label=f"Limit +/-{limit}")
                ax2.axhline(y=-limit, color="red", linestyle="--",
                            linewidth=0.8, alpha=0.6)
                limit_lines_drawn.add(limit)

    ax2.set_ylabel("Position")
    ax2.set_xlabel("Tick")
    handles, labels = ax2.get_legend_handles_labels()
    if handles:
        ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "pnl_chart.png")
    plt.savefig(out_path, dpi=150)
    print(f"[PLOT] Saved to {out_path}")
    plt.close()


# ================================================================
# Part 6: 主程序入口
# ================================================================

def run_backtest(filepath: str, output_dir: str = "."):
    """
    完整回测流程:
    1. 加载 CSV 数据，按 timestamp (+ day) 分组排序
    2. 逐 tick: 组装 TradingState -> 调用 Trader.run() -> 撮合 -> 算账
    3. 绘制 PnL 和仓位图, 日志和图表输出到 output_dir
    """
    df = load_csv(filepath)
    trader = Trader()

    # 固定随机种子: 保证回测结果可复现 (Deterministic)
    import random
    random.seed(42)

    # 全局状态
    positions = defaultdict(int)   # product -> 当前仓位
    cash = defaultdict(float)      # product -> 累计现金流
    trader_data = ""               # Trader 跨 tick 状态字符串
    last_valid_mid: dict = {}      # v5.4: forward-fill mid prices; prevents pos*0 MTM spike

    # 结果记录
    results = []
    positions_history = []

    # 按 (day, timestamp) 或仅 timestamp 分组排序
    if "day" in df.columns:
        sort_keys = ["day", "timestamp"]
        group_keys = ["day", "timestamp"]
    else:
        sort_keys = ["timestamp"]
        group_keys = ["timestamp"]

    df = df.sort_values(sort_keys)
    grouped = df.groupby(group_keys)
    total_ticks = len(grouped)
    print(f"[BACKTEST] {total_ticks} ticks to process")

    tick_index = 0

    for group_key, tick_df in grouped:
        # 提取实际 timestamp（多列分组时取最后一个元素）
        ts = int(group_key[-1]) if isinstance(group_key, tuple) else int(group_key)
        tick_index += 1

        # Step 1: 组装 TradingState
        state, mid_prices, market_bids, market_asks = build_state_for_tick(
            tick_df, positions, trader_data, ts
        )

        # Step 2: 调用 Trader（黑盒，不可修改）
        try:
            orders, conversions, trader_data = trader.run(state)
        except Exception as e:
            print(f"  [ERROR] Trader.run() failed at tick {ts}: {e}")
            orders = {}

        # Step 3: 撮合 + 算账
        fills = match_orders(orders, market_bids, market_asks, positions, cash)

        # Step 4: 盯市估值 (v5.4: forward-fill missing mid prices)
        for product, mp in mid_prices.items():
            if mp != 0.0:
                last_valid_mid[product] = mp
        filled_mid_prices = {}
        all_products = set(list(cash.keys()) + list(positions.keys()) + list(mid_prices.keys()))
        for p in all_products:
            if p in mid_prices and mid_prices[p] != 0.0:
                filled_mid_prices[p] = mid_prices[p]
            else:
                filled_mid_prices[p] = last_valid_mid.get(p, 0.0)
        pnl = calc_mtm_pnl(cash, positions, filled_mid_prices)

        # 记录本 tick 结果
        results.append({"tick": tick_index, "pnl": pnl, "fills": len(fills)})
        positions_history.append(dict(positions))

        # 打印成交明细
        if fills:
            for product, price, qty in fills:
                side = "BUY" if qty > 0 else "SELL"
                print(f"  [{ts}] {side} {product} @ {price} x {abs(qty)} "
                      f"-> pos={positions[product]}")

    # 输出最终汇总
    total_fills = sum(1 for r in results if r.get("fills", 0) > 0)
    final_pnl = results[-1]["pnl"] if results else 0
    print(f"\n[RESULT] {len(results)} ticks processed, {total_fills} ticks with fills, Final PnL = {final_pnl:.2f}")
    if total_fills == 0:
        print("[HINT] Zero fills. Maker orders inside spread won't cross market best quotes.")
        print("       This is expected for V1 conservative matching (taker-only fill model).")
    for p in sorted(positions.keys()):
        if positions[p] != 0 or cash[p] != 0:
            print(f"  {p}: pos={positions[p]}, cash={cash[p]:.2f}")

    # 绘图
    plot_results(results, positions_history, filepath, output_dir)

    # 保存 config 快照
    import json
    config_path = os.path.join(output_dir, "config_snap.json")
    with open(config_path, "w") as f:
        json.dump(TRADING_CONFIG, f, indent=2)
    print(f"[CONFIG] Saved to {config_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="IMC Prosperity 4 Local Backtester")
    parser.add_argument("csv", nargs="?",
                        default=os.path.join("data", "tutorial_round_data.csv"),
                        help="Path to prices CSV file")
    parser.add_argument("--output-dir", "-o", default=".",
                        help="Directory to save charts, logs, and config snapshot")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"[ERROR] File not found: {args.csv}")
        parser.print_help()
        sys.exit(1)

    run_backtest(args.csv, args.output_dir)
