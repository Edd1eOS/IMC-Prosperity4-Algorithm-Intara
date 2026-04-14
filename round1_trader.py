"""
round1_trader.py — IMC Prosperity 4 Round 1 策略
================================================
资产（Round 1 实际产品名）：
  ASH_COATED_OSMIUM    — 固定FV资产（FV=10000，std≈5，均值钉在10000，仓位±80）
  INTARIAN_PEPPER_ROOT — 趋势资产（每天涨+1000，需EMA动态FV，仓位±80）

核心逻辑：
  1. 状态反序列化：从 traderData 恢复 PEPPER_ROOT 价格历史
  2. ASH_COATED_OSMIUM：动态FV（慢EMA + 微观价格），主动吃单 + 非线性偏斜做市
  3. INTARIAN_PEPPER_ROOT：EMA+微观价格修正 = 动态FV，复用同一吃单+做市逻辑
  4. 防御：双层 try/except 隔离 + 最终头寸钳制
"""
# ================================================================
# CHANGELOG v5.4
# - OSM FV: 硬编码10000 → 慢EMA(alpha=0.05) + 微观价格混合; 冷启动期坚守10000
# - 库存偏斜: 线性 → 指数型 compute_skew(); |pos|≥75%*limit时指数放大
# - 单边报价: |pos|≥87.5%*limit(=70)时压制增仓方向的MM挂单; 仅作用于Phase 2
# - 移除冗余print语句，防止云端日志超限
# ================================================================

import json
import math
from datamodel import OrderDepth, TradingState, Order

# ================================================================
# 全局常量（Round 1 实际产品名）
# ================================================================
# --- ASH_COATED_OSMIUM：动态公允价值资产（v5.4 升级）---
# 三天数据验证：mean≈10000，std≈5，范围 9977-10023
OSM_FV           = 10_000    # 冷启动/盘口真空时的兜底公允价值
OSM_LIMIT        = 80        # 仓位硬上限（绝对值）
OSM_ALPHA        = 0.1       # 库存偏斜系数
OSM_EMA_ALPHA    = 0.05      # v5.4: 慢EMA平滑因子（约19期）；追踪长期漂移
OSM_MICRO_WEIGHT = 0.2       # v5.4: 微观价格权重（20%，比PPR更保守）
OSM_MIN_HISTORY  = 3         # v5.4: EMA预热最小历史点数

# --- INTARIAN_PEPPER_ROOT：趋势资产 ---
# 三天数据验证：每天上涨+1000，std≈288，需 EMA 追踪趋势
PPR_LIMIT = 80
PPR_ALPHA = 0.1
EMA_ALPHA    = 0.2           # EMA 平滑因子，等效约 9 期
MICRO_WEIGHT = 0.3           # 微观价格对最终动态FV的修正权重（30%）
MAX_HISTORY  = 20            # 最多保留的历史价格点数
MIN_HISTORY  = 3             # 历史点数不足时退化为纯微观价格
MAX_MM_LOT   = 15            # 单笔 MM 被动挂单上限（防止单次成交从极端到极端）

# --- v5.4: 非线性指数库存偏斜参数 ---
SKEW_K         = 2.0         # 超过阈值后的指数陡度
SKEW_THRESHOLD = 0.75        # 指数启动阈值（仓位 >= 75% * limit，即60/80）
ONE_SIDE_FRAC  = 0.875       # 单边报价阈值（仓位 >= 87.5% * limit，即70/80）

# 供 backtester.py 读取（绘图时标注仓位上下限用）
TRADING_CONFIG = {
    "ASH_COATED_OSMIUM":    {"limit": OSM_LIMIT, "alpha": OSM_ALPHA, "base_spread": 1},
    "INTARIAN_PEPPER_ROOT": {"limit": PPR_LIMIT, "alpha": PPR_ALPHA, "base_spread": 1},
}


# ================================================================
# 辅助函数
# ================================================================

def compute_ema(prices: list, alpha: float = EMA_ALPHA) -> float:
    """
    从价格列表计算指数移动平均线（EMA）。
    迭代公式：EMA_t = alpha * price_t + (1 - alpha) * EMA_{t-1}
    列表从旧到新排列（index 0 最旧，最后一个最新）。
    """
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return ema


def compute_skew(pos: int, alpha: float, limit: int,
                 k: float = SKEW_K,
                 threshold_frac: float = SKEW_THRESHOLD) -> int:
    """
    非线性指数库存偏斜（v5.4）。

    线性区（|pos| < threshold_frac * limit）：
        skew = sign(pos) * int(alpha * |pos|)          ← 与v5.3相同

    指数区（|pos| >= threshold_frac * limit）：
        excess = |pos| - threshold
        skew = sign(pos) * int(alpha * |pos| * exp(k * excess / limit))

    示例（limit=80, alpha=0.1, k=2.0, threshold=60）：
      pos=0  → 0    pos=40 → 4    pos=60 → 6
      pos=70 → 8    pos=78 → 12
    """
    abs_pos = abs(pos)
    threshold = threshold_frac * limit
    linear_part = alpha * abs_pos
    if abs_pos >= threshold:
        excess = abs_pos - threshold
        raw = linear_part * math.exp(k * excess / limit)
    else:
        raw = linear_part
    sign = 1 if pos > 0 else (-1 if pos < 0 else 0)
    return sign * int(raw)


def compute_microprice(order_depth: OrderDepth) -> float | None:
    """
    计算订单簿微观价格（Micro-price）= 量加权中间价。

    公式：micro = (best_bid * q_ask + best_ask * q_bid) / (q_bid + q_ask)

    直觉：
      - bid 量 >> ask 量 → 强买压 → micro 偏向 ask（价格倾向上涨）
      - ask 量 >> bid 量 → 强卖压 → micro 偏向 bid（价格倾向下跌）

    buy_orders 存正量，sell_orders 存负量（IMC 平台惯例）。
    """
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return None
    best_bid = max(order_depth.buy_orders.keys())
    best_ask = min(order_depth.sell_orders.keys())
    q_bid = abs(order_depth.buy_orders[best_bid])    # 取绝对值确保正数
    q_ask = abs(order_depth.sell_orders[best_ask])   # 取绝对值
    total = q_bid + q_ask
    if total == 0:
        return (best_bid + best_ask) / 2.0
    return (best_bid * q_ask + best_ask * q_bid) / total


def aggressive_take_and_mm(
    symbol: str,
    order_depth: OrderDepth,
    fair_value: float,
    position: int,
    limit: int,
    alpha: float,
) -> list:
    """
    核心交易逻辑：主动吃单 + 库存偏斜被动做市。

    Phase 1 — 主动吃单（Taker，V3引擎100%成交）：
      · 买入所有严格低于 FV 的 ask 价位（价格越低越优先）
      · 卖出所有严格高于 FV 的 bid 价位（价格越高越优先）
      · 每次下单量由剩余仓位额度决定，确保不越界

    Phase 2 — 库存偏斜被动做市（Maker，30%/10%概率成交）：
      · 计算剩余额度，将所有可用额度集中成一笔挂单
      · 挂单价格围绕 FV±1，并根据净仓位方向做偏斜
        skew = int(alpha * sim_pos)
        mm_bid = fv - 1 - skew  （持多则压低买价，鼓励成交更多卖单）
        mm_ask = fv + 1 - skew

    返回：list[Order]
    """
    orders = []
    sim_pos = position          # 模拟仓位，跟踪挂单后的预期净仓位
    fv_int  = round(fair_value) # 整数化公允价值，用于价格比较

    # ---------- Phase 1a: 主动买入（吃低于FV的ask）----------
    for ask_price in sorted(order_depth.sell_orders.keys()):
        if ask_price >= fv_int:
            break  # ask 已排序，到达 FV 及以上时停止
        available_vol = abs(order_depth.sell_orders[ask_price])
        buy_capacity  = limit - sim_pos       # 还能买多少手
        vol = min(available_vol, buy_capacity)
        if vol <= 0:
            break  # 仓位已满，无法继续买入
        orders.append(Order(symbol, ask_price, vol))
        sim_pos += vol

    # ---------- Phase 1b: 主动卖出（吃高于FV的bid）----------
    for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
        if bid_price <= fv_int:
            break  # bid 已倒序，到达 FV 及以下时停止
        available_vol = order_depth.buy_orders[bid_price]
        sell_capacity = limit + sim_pos       # 还能卖多少手（仓位越负越少）
        vol = min(available_vol, sell_capacity)
        if vol <= 0:
            break  # 仓位已到下限，无法继续卖出
        orders.append(Order(symbol, bid_price, -vol))
        sim_pos -= vol

    # ---------- Phase 2: 非线性指数库存偏斜被动做市（v5.4）----------
    # 注意：单边报价压制仅作用于此处的 Maker 挂单，不影响 Phase 1 的 Taker 吃单
    skew   = compute_skew(sim_pos, alpha, limit)   # v5.4: 指数偏斜替换线性偏斜
    mm_bid = fv_int - 1 - skew
    mm_ask = fv_int + 1 - skew

    # ---- 关键约束：MM 报价绝不能穿越盘口，防止被 V3 引擎识别为 Taker ----
    best_bid_now = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
    best_ask_now = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
    if best_ask_now is not None:
        mm_bid = min(mm_bid, best_ask_now - 1)
    if best_bid_now is not None:
        mm_ask = max(mm_ask, best_bid_now + 1)

    # 安全：防止 bid >= ask 导致价格倒挂
    if mm_bid >= mm_ask:
        mm_bid = fv_int - 1
        mm_ask = fv_int + 1

    # 剩余额度，但每笔 MM 上限为 MAX_MM_LOT，防止单次成交从极端到极端
    buy_cap  = min(limit - sim_pos, MAX_MM_LOT)
    sell_cap = min(limit + sim_pos, MAX_MM_LOT)

    # ---- v5.4: 单边报价压制（仅 Maker 层）----
    # 仓位 >= ONE_SIDE_FRAC * limit（即 70/80）时，压制增仓方向的挂单
    one_side_thresh = int(ONE_SIDE_FRAC * limit)   # = 70 for limit=80
    if sim_pos >= one_side_thresh:
        buy_cap = 0    # 深度持多：停止挂买单，只挂卖单平仓
    if sim_pos <= -one_side_thresh:
        sell_cap = 0   # 深度持空：停止挂卖单，只挂买单平仓

    if buy_cap > 0:
        orders.append(Order(symbol, mm_bid, buy_cap))
    if sell_cap > 0:
        orders.append(Order(symbol, mm_ask, -sell_cap))

    return orders


# ================================================================
# Trader 主类
# ================================================================

class Trader:

    def run(self, state: TradingState) -> tuple:
        """
        主入口：返回 (orders_dict, conversions, trader_data_str)

        四个模块按顺序执行：
          1. 反序列化历史状态
          2. EMERALDS 吃单+做市（try/except 隔离）
          3. TOMATOES EMA动态FV吃单+做市（try/except 隔离）
          4. 最终头寸钳制兜底 + 序列化状态
        """
        result: dict[str, list] = {}

        # ============================================================
        # Module 1: 状态反序列化（State Deserialization）
        # 从 traderData JSON 字符串中恢复 PEPPER_ROOT 价格历史列表
        # 任何解析失败都静默处理，初始化为空字典，保证程序不崩溃
        # ============================================================
        try:
            memory: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            memory = {}

        # INTARIAN_PEPPER_ROOT 历史价格列表，从旧到新排列
        ppr_history: list = memory.get("ppr_history", [])
        # ASH_COATED_OSMIUM 历史微观价格列表（v5.4: 动态FV用）
        osm_history: list = memory.get("osm_history", [])

        # ============================================================
        # Module 2: ASH_COATED_OSMIUM — 动态FV做市（v5.4）
        # FV = 慢EMA(alpha=0.05) * 0.8 + 微观价格 * 0.2
        # 冷启动（历史不足3点）或盘口真空时坚守硬编码 OSM_FV=10000
        # ============================================================
        try:
            SYM_OSM = "ASH_COATED_OSMIUM"
            if SYM_OSM in state.order_depths:
                od_osm  = state.order_depths[SYM_OSM]
                pos_osm = state.position.get(SYM_OSM, 0)

                # --- 2a: 计算微观价格 ---
                micro_osm = compute_microprice(od_osm)
                if micro_osm is None and od_osm.buy_orders and od_osm.sell_orders:
                    micro_osm = (max(od_osm.buy_orders) + min(od_osm.sell_orders)) / 2.0

                # --- 2b: 更新历史列表 ---
                if micro_osm is not None:
                    osm_history.append(micro_osm)
                    if len(osm_history) > MAX_HISTORY:
                        osm_history = osm_history[-MAX_HISTORY:]

                # --- 2c: 计算动态FV (Patch 2: 冷启动坚守理论均值) ---
                if micro_osm is not None and len(osm_history) >= OSM_MIN_HISTORY:
                    osm_slow_ema = compute_ema(osm_history, alpha=OSM_EMA_ALPHA)
                    osm_fv = (1.0 - OSM_MICRO_WEIGHT) * osm_slow_ema + OSM_MICRO_WEIGHT * micro_osm
                else:
                    osm_fv = OSM_FV   # 冷启动或盘口真空：持守理论均值10000

                # --- 2d: 下单 ---
                osm_orders = aggressive_take_and_mm(
                    SYM_OSM, od_osm, osm_fv, pos_osm, OSM_LIMIT, OSM_ALPHA
                )
                if osm_orders:
                    result[SYM_OSM] = osm_orders
        except Exception as e:
            print(f"OSM ERROR: {e}")

        # ============================================================
        # Module 3: INTARIAN_PEPPER_ROOT — 动态公允价值策略
        # 特征：强趋势资产，每天上涨+1000（约0.1/tick），std≈288
        # 步骤：
        #   a. 计算当前 tick 微观价格（Micro-price）
        #   b. 将微观价格压入历史列表，保持不超过 MAX_HISTORY
        #   c. 若历史足够，用 EMA 作为主锚，微观价格小幅修正
        #   d. 复用 aggressive_take_and_mm 逻辑
        # ============================================================
        try:
            SYM_PPR = "INTARIAN_PEPPER_ROOT"
            if SYM_PPR in state.order_depths:
                od_ppr  = state.order_depths[SYM_PPR]
                pos_ppr = state.position.get(SYM_PPR, 0)

                # --- 3a: 计算当前微观价格 ---
                micro = compute_microprice(od_ppr)
                if micro is None:
                    # 极端情况（单边盘口）：退化为普通中间价
                    if od_ppr.buy_orders and od_ppr.sell_orders:
                        micro = (max(od_ppr.buy_orders) + min(od_ppr.sell_orders)) / 2.0

                # --- 3b: 更新历史（先加入当前价格，再计算EMA）---
                if micro is not None:
                    ppr_history.append(micro)
                    if len(ppr_history) > MAX_HISTORY:
                        ppr_history = ppr_history[-MAX_HISTORY:]

                # --- 3c: 计算动态公允价值 ---
                if micro is not None and len(ppr_history) >= MIN_HISTORY:
                    ema = compute_ema(ppr_history)
                    # 70% EMA（趋势稳定性）+ 30% 微观价格（当前买卖压力修正）
                    dynamic_fv = (1.0 - MICRO_WEIGHT) * ema + MICRO_WEIGHT * micro
                elif micro is not None:
                    # 历史不足：纯微观价格作为FV
                    dynamic_fv = micro
                else:
                    dynamic_fv = None

                # --- 3d: 下单 ---
                if dynamic_fv is not None:
                    ppr_orders = aggressive_take_and_mm(
                        SYM_PPR, od_ppr, dynamic_fv, pos_ppr, PPR_LIMIT, PPR_ALPHA
                    )
                    if ppr_orders:
                        result[SYM_PPR] = ppr_orders
        except Exception as e:
            # PEPPER_ROOT 异常：打印错误，OSM 已生成的订单照常返回
            print(f"PPR ERROR: {e}")

        # ============================================================
        # Module 4: 最终头寸钳制（Last-resort Position Clamping）
        # aggressive_take_and_mm 内部已控制不越界，此处是额外安全网
        # 遍历所有生成的订单，截断任何会导致越界的量
        # ============================================================
        for sym, orders_list in result.items():
            limit = TRADING_CONFIG.get(sym, {}).get("limit", 80)
            sim   = state.position.get(sym, 0)
            clamped = []

            for order in orders_list:
                if order.quantity > 0:                   # 买单
                    max_buy = limit - sim                # 最多还能买几手
                    vol = min(order.quantity, max_buy)
                    if vol > 0:
                        clamped.append(Order(sym, order.price, vol))
                        sim += vol
                elif order.quantity < 0:                 # 卖单
                    max_sell = limit + sim               # 最多还能卖几手
                    vol = min(abs(order.quantity), max_sell)
                    if vol > 0:
                        clamped.append(Order(sym, order.price, -vol))
                        sim -= vol

            result[sym] = clamped

        # ============================================================
        # 序列化状态并返回
        # ============================================================
        memory["ppr_history"] = ppr_history
        memory["osm_history"] = osm_history   # v5.4: persist OSM micro-price history
        trader_data = json.dumps(memory)

        return result, 0, trader_data
