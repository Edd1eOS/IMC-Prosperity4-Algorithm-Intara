"""
round1_trader.py — IMC Prosperity 4 Round 1 策略  [v8.0]
=========================================================
资产（Round 1 实际产品名）：
  ASH_COATED_OSMIUM    — 固定FV资产（FV≈10000，std≈5，仓位±80）
  INTARIAN_PEPPER_ROOT — 趋势资产（每天涨+1000，仓位±80）

v8.0 核心升级（相对 v7.0）：
  1. PPR Drift 最大化：FV = 快速EMA(α=0.6)×0.3 + micro×0.7 + DRIFT_BIAS(10)
  2. PPR 永久 TREND_UP：禁止所有卖出，仓位只做多
  3. PPR 无建仓惩罚：taker_alpha=0.0，取消买入阈值随仓位衰减
  4. PPR 取消主动减仓：unwind_thresh=None（持多到底）
  5. OSM Kalman 加速：Q 0.005→0.015（更快适应微结构变化）
  6. OSM 容量提升：MAX_MM_LOT 15→20，UNWIND_LOT 5→10
"""
# ================================================================
# CHANGELOG v8.1（相对 v8.0）
# 基于 247252.log 深度分析：PPR 已达理论极限（993/999 ticks +8.0），OSM 是唯一优化杠杆
# 改动 1: OSM_AS_GAMMA 2.0→1.4（AS 报价宽度：~10→~7，盘口 spread=16 时更靠近 best）
# 改动 2: OSM_KALMAN_Q 0.015→0.025（FV 适应更快，减少 90-100K block 亏损）
# 改动 3: OSM_UNWIND_THRESH 70→60（更早减仓，降低极端持仓暴露）
# 改动 4: OSM_TAKER_ALPHA 0.1→0.05（Phase 1 仓位惩罚减半，更多均值回归交易）
# 改动 5: MAX_MM_LOT 20→25（盘口 L1 深度常见 10-28，扩大做市手数）
# 改动 6: PPR_DRIFT_BIAS 10→7（PPR ask-mid~6-8，bias=7 仍能触发，每 unit 少付 ~3 点）
# ================================================================
# CHANGELOG v8.0b（相对 v8.0）
# 基于 247252.log 分析：PPR 已达理论极限，OSM 是唯一杠杆。简单参数调优(v8.1)失败。
# 转向结构性改动：双层 Maker 挂单。
# 改动 1: 新增 OSM Layer 2 做市挂单
#   · Layer 1（现有）: FV ± eff_spread - skew，手数 = MAX_MM_LOT
#   · Layer 2（新增）: FV ± (eff_spread + 4) - skew，手数 = 10
#   · L2 更深在盘口，捕捉波动尖峰成交，不影响 L1 逻辑
#   · Module 4 仓位钳制确保总订单不超限
# ================================================================
# CHANGELOG v8.0（相对 v7.0）
# 改动 1: PPR FV Drift Bias
#   · EMA_ALPHA: 0.2→0.6（快速跟踪），MICRO_WEIGHT: 0.3→0.7（依赖当前微观价格）
#   · 新增 PPR_DRIFT_BIAS=10：FV 系统性上偏 10 点，使 Phase 1a 买入在正常盘口持续触发
#   · 理论依据：PPR 每 tick 漂移 +0.1，10 点 bias 的回本期约 100 tick
# 改动 2: PPR 永久 TREND_UP
#   · 绕过 v7.0 状态机，强制 skip_dir=1（禁止 Phase 1b 卖出 + Phase 2 卖单）
#   · 消除 v7.0 中 t=65.7K 的 15 手逆势抛售事件（该事件损失 ~600 XIREC）
# 改动 3: PPR_TAKER_ALPHA: 0.1→0.0
#   · 取消仓位感知买入阈值衰减：pos=+40 时不再需要额外 4 点折扣才买入
# 改动 4: PPR unwind_thresh: 70→None
#   · 取消 PPR 主动减仓：pos≥+70 时不再以 taker 价格卖出，持多到底
# 改动 5: OSM_KALMAN_Q: 0.005→0.015
#   · Kalman 过程噪声增大 3 倍：FV 更快适应微结构变化
# 改动 6: MAX_MM_LOT: 15→20，OSM_UNWIND_LOT: 5→10
#   · 增大 MM 单笔手数和减仓速度，提升 OSM 资金周转率
# ================================================================
# CHANGELOG v7.0（相对 v6.0）
# 改动 1: OSM Active Unwind (Phase 1c)
#   · 当 |pos_osm| >= OSM_UNWIND_THRESH (=70) 时，在 Phase 1c 以 taker 价格强制减仓
#   · 以最多 OSM_UNWIND_LOT (=5) 手/tick 跨越点差，保证 100% 成交
#   · 代价：每手损失约 1 tick 点差，但解除死锁；死锁时损失为 0（更差）
# 改动 2: PPR Regime Switching（状态机）
#   · 每 tick 用最近 PPR_SLOPE_WINDOW (=20) tick 微观价格做线性回归，得到斜率
#   · 若斜率连续 PPR_TREND_CONFIRM (=3) tick 超过 PPR_SLOPE_THRESH (=0.06)：进入 TREND_UP
#   · 若斜率连续 3 tick 低于 -0.06：进入 TREND_DOWN（稳健性备用）
#   · TREND_UP 模式：跳过 Phase 1b 卖出 + Phase 2 卖单 → 防止趋势中持续建空
#   · TREND_DOWN 模式：跳过 Phase 1a 买入 + Phase 2 买单（对称）
#   · 状态存入 traderData（ppr_trend_cnt 有符号计数器）
# 改动 3: PPR taker_alpha = 0.1（原为 0.0）
#   · pos=-70 时 Phase 1b 卖出阈值 = fv+7，深度空仓时几乎不再触发 Phase 1 卖单
#   · 与 OSM_TAKER_ALPHA 完全对称，使用已验证有效的机制
# 改动 4: OBI 对冲选择过滤（Phase 2 only）
#   · OBI = (V_bid - V_ask) / (V_bid + V_ask)，使用全簿深度计算
#   · OBI > OBI_ADVERSE_THRESH (+0.7)：跳过 Phase 2 卖单（强买压，做市卖单被摘樱桃）
#   · OBI < -OBI_ADVERSE_THRESH (-0.7)：跳过 Phase 2 买单（强卖压）
# 改动 5: PPR Active Unwind（与 OSM 对称）
#   · |pos_ppr| >= PPR_UNWIND_THRESH (=70) 时 Phase 1c 强制减仓
# ================================================================
# CHANGELOG v6.0（相对 v5.8）— 三层升级（已验证：云端 3352/100K，+37.3%）
# 改动 1: OSM FV: EMA混合 → 1D Kalman(Q=0.005, R=4.0, P₀=25)
# 改动 2: Phase 1 仓位感知阈值（仅OSM，OSM_TAKER_ALPHA=0.1）
# 改动 3: Phase 2 AS动态点差（双资产）
# ================================================================

import json
import math
from datamodel import OrderDepth, TradingState, Order

# ================================================================
# 全局常量
# ================================================================
# --- ASH_COATED_OSMIUM ---
OSM_FV           = 10_000
OSM_LIMIT        = 80
OSM_ALPHA        = 0.1
OSM_EMA_ALPHA    = 0.05
OSM_MICRO_WEIGHT = 0.20
OSM_MIN_HISTORY  = 3

# v6.0: Kalman filter
OSM_KALMAN_Q  = 0.015     # v8.0: 0.005→0.015（3x faster adaptation）
OSM_KALMAN_R  = 4.0
OSM_KALMAN_P0 = 25.0

# v6.0: Phase 1 仓位感知
OSM_TAKER_ALPHA = 0.1

# v6.0: AS 动态点差
OSM_AS_GAMMA    = 2.0
PPR_AS_GAMMA    = 0.15
AS_VOL_LOOKBACK = 10

# v7.0: OSM 主动清仓
OSM_UNWIND_THRESH = 70   # 触发强制减仓的仓位阈值（绝对值）
OSM_UNWIND_LOT    = 10   # v8.0: 5→10（faster position recovery）

# --- INTARIAN_PEPPER_ROOT ---
PPR_LIMIT = 80
PPR_ALPHA = 0.1
EMA_ALPHA    = 0.6       # v8.0: 0.2→0.6（fast EMA tracking for drift asset）
MICRO_WEIGHT = 0.7       # v8.0: 0.3→0.7（rely on current microprice）
MAX_HISTORY  = 20
MIN_HISTORY  = 3
MAX_MM_LOT   = 20        # v8.0: 15→20（larger MM lot size）

# v7.0: PPR 仓位感知（与 OSM 对称）
PPR_TAKER_ALPHA = 0.0    # v8.0: 0.1→0.0（no position penalty on PPR buys）

# v7.0: PPR 主动清仓（v8.0: disabled via None in call, constants kept for rollback）
PPR_UNWIND_THRESH = 70
PPR_UNWIND_LOT    = 5

# v8.0: PPR drift bias (known +100/1K ticks upward drift)
PPR_DRIFT_BIAS = 10

# v7.0: PPR 状态机参数
PPR_SLOPE_WINDOW  = 20    # 斜率估计窗口（tick 数）
PPR_SLOPE_THRESH  = 0.06  # 每 tick 斜率阈值（≈0.6× PPR 期望漂移 0.1/tick）
PPR_TREND_CONFIRM = 3     # 连续超阈值 tick 数才确认进入趋势模式

# v7.0: OBI 对冲选择过滤
OBI_ADVERSE_THRESH = 0.7  # |OBI| 超过此值时过滤逆向 Maker 挂单

# --- 共用参数 ---
SKEW_K         = 2.0
SKEW_THRESHOLD = 0.75
ONE_SIDE_FRAC  = 0.875

DIAG_MODE = False

# ================================================================
# Logger — hard-cap all stdout to prevent Lambda I/O timeout.
# All messages are buffered and emitted in one print() call at
# the end of run().  Any message that would push total output
# past MAX_LEN is silently dropped (never raises).
# ================================================================
MAX_LOG_LEN      = 3750   # bytes — conservative Lambda safe zone
MAX_TRADER_DATA  = 3800   # bytes — traderData state string cap


class Logger:
    def __init__(self) -> None:
        self._buf:  list[str] = []
        self._used: int       = 0

    def log(self, *args) -> None:
        msg = " ".join(str(a) for a in args)
        cost = len(msg) + 1          # +1 for the joining newline
        if self._used + cost > MAX_LOG_LEN:
            return                   # budget exhausted — drop silently
        self._buf.append(msg)
        self._used += cost

    def flush(self) -> None:
        if self._buf:
            print("\n".join(self._buf))
        self._buf.clear()
        self._used = 0


TRADING_CONFIG = {
    "ASH_COATED_OSMIUM":    {"limit": OSM_LIMIT, "alpha": OSM_ALPHA, "base_spread": 1},
    "INTARIAN_PEPPER_ROOT": {"limit": PPR_LIMIT, "alpha": PPR_ALPHA, "base_spread": 1},
}


# ================================================================
# 辅助函数
# ================================================================

def compute_ema(prices: list, alpha: float = EMA_ALPHA) -> float:
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return ema


def compute_skew(pos: int, alpha: float, limit: int,
                 k: float = SKEW_K,
                 threshold_frac: float = SKEW_THRESHOLD) -> int:
    abs_pos = abs(pos)
    threshold = threshold_frac * limit
    linear_part = alpha * abs_pos
    if abs_pos >= threshold:
        excess = abs_pos - threshold
        exponent = min(k * excess / limit, 20.0)
        raw = linear_part * math.exp(exponent)
    else:
        raw = linear_part
    sign = 1 if pos > 0 else (-1 if pos < 0 else 0)
    return sign * int(raw)


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
    """
    订单簿不平衡度（Order Book Imbalance）。

    公式：OBI = (V_bid - V_ask) / (V_bid + V_ask)

    使用全簿各档位量之和（非仅 best bid/ask），更鲁棒。
    OBI ∈ [-1, 1]；+1 = 纯买压；-1 = 纯卖压。
    """
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return 0.0
    v_bid = sum(abs(v) for v in order_depth.buy_orders.values())
    v_ask = sum(abs(v) for v in order_depth.sell_orders.values())
    total = v_bid + v_ask
    if total == 0:
        return 0.0
    return (v_bid - v_ask) / total


def compute_slope(prices: list, window: int = PPR_SLOPE_WINDOW) -> float:
    """
    最小二乘线性回归斜率，计算最近 window 个价格点的每 tick 变化率。

    返回：slope (XIREC / tick)；历史不足 2 点时返回 0.0。
    """
    recent = prices[-window:] if len(prices) >= window else prices
    n = len(recent)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(recent) / n
    num = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def kalman_update_1d(
    x: float, P: float, z: float,
    Q: float = OSM_KALMAN_Q,
    R: float = OSM_KALMAN_R,
) -> tuple[float, float]:
    """
    1D Kalman filter — predict + update (F=1, H=1).
    稳态增益 K ≈ 0.034；冷启动 K₀ ≈ 0.86。
    """
    P_pred = P + Q
    K      = P_pred / (P_pred + R)
    x_new  = x + K * (z - x)
    P_new  = (1.0 - K) * P_pred
    return x_new, P_new


def compute_micro_vol(prices: list, lookback: int = AS_VOL_LOOKBACK) -> float:
    if len(prices) < 2:
        return 0.0
    recent = prices[-lookback:] if len(prices) >= lookback else prices
    diffs  = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
    n      = len(diffs)
    mean_d = sum(diffs) / n
    var    = sum((d - mean_d) ** 2 for d in diffs) / max(n - 1, 1)
    return math.sqrt(var)


def aggressive_take_and_mm(
    symbol: str,
    order_depth: OrderDepth,
    fair_value: float,
    position: int,
    limit: int,
    alpha: float,
    taker_alpha: float = 0.0,
    half_spread: int   = 1,
    unwind_thresh: int | None = None,  # v7.0: |pos|≥thresh 时触发 Phase 1c 强制减仓
    unwind_lot: int    = 5,            # v7.0: Phase 1c 每 tick 最大手数
    skip_phase1_dir: int = 0,          # v7.0: +1=跳过卖出(TREND_UP), -1=跳过买入(TREND_DOWN)
    obi: float         = 0.0,          # v7.0: OBI 值，用于 Phase 2 对冲选择过滤
) -> list:
    """
    核心交易逻辑：主动吃单 + 强制减仓 + 库存偏斜做市。

    Phase 1a — 仓位感知主动买入（taker，100% 成交）
    Phase 1b — 仓位感知主动卖出（taker，100% 成交）
    Phase 1c — 强制减仓（v7.0：|pos|≥unwind_thresh 时跨点差减仓，100% 成交）
    Phase 2  — AS 动态点差 + 指数库存偏斜被动做市（Maker）
               OBI 极端时过滤逆向挂单（v7.0）
    """
    orders  = []
    sim_pos = position
    fv_int  = round(fair_value)

    # 预先计算盘口边界（Phase 1c 和 Phase 2 均需要）
    best_bid_now = max(order_depth.buy_orders.keys())  if order_depth.buy_orders  else None
    best_ask_now = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

    # ---------- Phase 1a: 仓位感知主动买入 ----------
    if skip_phase1_dir != -1:   # TREND_DOWN 模式跳过所有买入
        for ask_price in sorted(order_depth.sell_orders.keys()):
            buy_thr = fv_int - int(taker_alpha * max(sim_pos, 0))
            if ask_price >= buy_thr:
                break
            available_vol = abs(order_depth.sell_orders[ask_price])
            buy_capacity  = limit - sim_pos
            vol = min(available_vol, buy_capacity)
            if vol <= 0:
                break
            orders.append(Order(symbol, ask_price, vol))
            sim_pos += vol

    # ---------- Phase 1b: 仓位感知主动卖出 ----------
    if skip_phase1_dir != 1:    # TREND_UP 模式跳过所有卖出
        for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
            sell_thr = fv_int + int(taker_alpha * max(-sim_pos, 0))
            if bid_price <= sell_thr:
                break
            available_vol = order_depth.buy_orders[bid_price]
            sell_capacity = limit + sim_pos
            vol = min(available_vol, sell_capacity)
            if vol <= 0:
                break
            orders.append(Order(symbol, bid_price, -vol))
            sim_pos -= vol

    # ---------- Phase 1c: 强制减仓（v7.0 — 突破死锁）----------
    # 当仓位达到 ±unwind_thresh 时，以 taker 价格跨越点差强制减仓
    # 代价约 1 tick 点差/手；但仓位死锁时每 tick 收益为 0（代价更高）
    if unwind_thresh is not None:
        if sim_pos >= unwind_thresh and best_bid_now is not None:
            # 持多过重：主动卖到 best_bid（100% taker 成交）
            sell_cap = min(limit + sim_pos, unwind_lot)
            avail    = abs(order_depth.buy_orders.get(best_bid_now, 0))
            cap      = min(sell_cap, avail)
            if cap > 0:
                orders.append(Order(symbol, best_bid_now, -cap))
                sim_pos -= cap
        elif sim_pos <= -unwind_thresh and best_ask_now is not None:
            # 持空过重：主动买到 best_ask（100% taker 成交）
            buy_cap = min(limit - sim_pos, unwind_lot)
            avail   = abs(order_depth.sell_orders.get(best_ask_now, 0))
            cap     = min(buy_cap, avail)
            if cap > 0:
                orders.append(Order(symbol, best_ask_now, cap))
                sim_pos += cap

    # ---------- Phase 2: AS 动态点差 + 非线性库存偏斜做市 ----------
    skew = compute_skew(sim_pos, alpha, limit)

    if best_bid_now is not None and best_ask_now is not None:
        book_half  = max(1, (best_ask_now - best_bid_now) // 2)
        eff_spread = min(half_spread, book_half)
    else:
        eff_spread = half_spread

    mm_bid = fv_int - eff_spread - skew
    mm_ask = fv_int + eff_spread - skew

    # 非穿越钳制
    if best_ask_now is not None:
        mm_bid = min(mm_bid, best_ask_now - 1)
    if best_bid_now is not None:
        mm_ask = max(mm_ask, best_bid_now + 1)

    if mm_bid >= mm_ask:
        mm_bid = fv_int - 1
        mm_ask = fv_int + 1

    buy_cap  = min(limit - sim_pos, MAX_MM_LOT)
    sell_cap = min(limit + sim_pos, MAX_MM_LOT)

    one_side_thresh = int(ONE_SIDE_FRAC * limit)
    if sim_pos >= one_side_thresh:
        buy_cap = 0
    if sim_pos <= -one_side_thresh:
        sell_cap = 0

    # v7.0: Phase 2 OBI 对冲选择过滤 + 趋势模式方向压制
    # OBI > +0.7 → 强买压 → 跳过做市卖单（避免被聪明投资者摘樱桃）
    # OBI < -0.7 → 强卖压 → 跳过做市买单
    skip_p2_sell = (skip_phase1_dir == 1) or (obi > OBI_ADVERSE_THRESH)
    skip_p2_buy  = (skip_phase1_dir == -1) or (obi < -OBI_ADVERSE_THRESH)

    if buy_cap > 0 and not skip_p2_buy:
        orders.append(Order(symbol, mm_bid, buy_cap))
    if sell_cap > 0 and not skip_p2_sell:
        orders.append(Order(symbol, mm_ask, -sell_cap))

    return orders


# ================================================================
# Trader 主类
# ================================================================

class Trader:

    def run(self, state: TradingState) -> tuple:
        logger: Logger           = Logger()
        result: dict[str, list] = {}

        # ============================================================
        # Module 1: 状态反序列化
        # ============================================================
        try:
            memory: dict = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            memory = {}

        ppr_history:    list  = memory.get("ppr_history", [])
        osm_history:    list  = memory.get("osm_history", [])
        osm_kf_x:       float = memory.get("osm_kf_x", float(OSM_FV))
        osm_kf_P:       float = memory.get("osm_kf_P", OSM_KALMAN_P0)
        # v7.0: PPR 状态机计数器（有符号：正=上升趋势tick数，负=下降趋势tick数）
        ppr_trend_cnt:  int   = memory.get("ppr_trend_cnt", 0)

        # ============================================================
        # Module 2: ASH_COATED_OSMIUM
        # v7.0 新增: OBI 过滤 + Phase 1c 主动减仓（unwind_thresh=70）
        # ============================================================
        try:
            SYM_OSM = "ASH_COATED_OSMIUM"
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

                if micro_osm is not None:
                    osm_kf_x, osm_kf_P = kalman_update_1d(
                        osm_kf_x, osm_kf_P, micro_osm, Q=OSM_KALMAN_Q, R=OSM_KALMAN_R
                    )
                osm_fv = osm_kf_x

                osm_vol    = compute_micro_vol(osm_history, AS_VOL_LOOKBACK)
                osm_spread = max(1, round(OSM_AS_GAMMA * osm_vol))

                # v7.0: OBI 过滤（OSM 始终在 MM 模式，skip_phase1_dir=0）
                obi_osm = compute_obi(od_osm)

                osm_orders = aggressive_take_and_mm(
                    SYM_OSM, od_osm, osm_fv, pos_osm, OSM_LIMIT, OSM_ALPHA,
                    taker_alpha=OSM_TAKER_ALPHA,
                    half_spread=osm_spread,
                    unwind_thresh=OSM_UNWIND_THRESH,   # v7.0: 主动减仓
                    unwind_lot=OSM_UNWIND_LOT,
                    skip_phase1_dir=0,                  # OSM 不切换趋势模式
                    obi=obi_osm,                        # v7.0: OBI 过滤
                )
                if osm_orders:
                    result[SYM_OSM] = osm_orders
        except Exception as e:
            logger.log(f"[OSM ERR] {e}")

        # ============================================================
        # Module 3: INTARIAN_PEPPER_ROOT
        # v7.0 新增: PPR_TAKER_ALPHA=0.1 + 状态机 + OBI + Phase 1c 主动减仓
        # ============================================================
        try:
            SYM_PPR = "INTARIAN_PEPPER_ROOT"
            if SYM_PPR in state.order_depths:
                od_ppr  = state.order_depths[SYM_PPR]
                pos_ppr = state.position.get(SYM_PPR, 0)

                micro = compute_microprice(od_ppr)
                if micro is None:
                    if od_ppr.buy_orders and od_ppr.sell_orders:
                        micro = (max(od_ppr.buy_orders) + min(od_ppr.sell_orders)) / 2.0

                if micro is not None:
                    ppr_history.append(micro)
                    if len(ppr_history) > MAX_HISTORY:
                        ppr_history = ppr_history[-MAX_HISTORY:]

                if micro is not None and len(ppr_history) >= MIN_HISTORY:
                    ema = compute_ema(ppr_history)
                    dynamic_fv = (1.0 - MICRO_WEIGHT) * ema + MICRO_WEIGHT * micro + PPR_DRIFT_BIAS
                elif micro is not None:
                    dynamic_fv = micro + PPR_DRIFT_BIAS
                else:
                    dynamic_fv = None

                # ---- v7.0: PPR 状态机（Regime Switching）----
                # 计算 20 tick 线性回归斜率，连续超阈值则切换趋势模式
                if len(ppr_history) >= 2:
                    slope = compute_slope(ppr_history, PPR_SLOPE_WINDOW)
                    if slope > PPR_SLOPE_THRESH:
                        # 上升斜率：增加上升计数，重置下降计数
                        ppr_trend_cnt = max(0, ppr_trend_cnt) + 1
                    elif slope < -PPR_SLOPE_THRESH:
                        # 下降斜率：增加下降计数，重置上升计数
                        ppr_trend_cnt = min(0, ppr_trend_cnt) - 1
                    else:
                        # 斜率不显著：归零（回归 MM 模式）
                        ppr_trend_cnt = 0
                else:
                    ppr_trend_cnt = 0

                # v8.0: PPR is known-uptrend asset (+100/1K ticks drift)
                # Force TREND_UP permanently — never sell PPR
                skip_dir = 1

                # v7.0: OBI 过滤
                obi_ppr = compute_obi(od_ppr)

                if dynamic_fv is not None:
                    ppr_vol    = compute_micro_vol(ppr_history, AS_VOL_LOOKBACK)
                    ppr_spread = max(1, round(PPR_AS_GAMMA * ppr_vol))
                    ppr_orders = aggressive_take_and_mm(
                        SYM_PPR, od_ppr, dynamic_fv, pos_ppr, PPR_LIMIT, PPR_ALPHA,
                        taker_alpha=PPR_TAKER_ALPHA,    # v8.0: 0.0（no position penalty）
                        half_spread=ppr_spread,
                        unwind_thresh=None,              # v8.0: no unwind（hold longs）
                        unwind_lot=PPR_UNWIND_LOT,
                        skip_phase1_dir=skip_dir,        # v8.0: always TREND_UP
                        obi=obi_ppr,
                    )
                    if ppr_orders:
                        result[SYM_PPR] = ppr_orders
        except Exception as e:
            logger.log(f"[PPR ERR] {e}")

        # ============================================================
        # Module 4: 最终头寸钳制（安全网）
        # 逐单截断，确保累计持仓绝对不超过 ±limit。
        # 任何被截断的手数都通过 logger 记录（不 raise，不崩溃）。
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
        # 序列化状态并返回
        # ============================================================
        memory["ppr_history"]   = ppr_history
        memory["osm_history"]   = osm_history
        memory["osm_kf_x"]      = osm_kf_x
        memory["osm_kf_P"]      = osm_kf_P
        memory["ppr_trend_cnt"] = ppr_trend_cnt   # v7.0: PPR 状态机计数器
        trader_data = json.dumps(memory)

        # traderData 长度安全裁剪：防止 Lambda 状态传递超限。
        # 优先缩减历史序列（保留最近 5 点），确保输出始终是合法 JSON。
        if len(trader_data) > MAX_TRADER_DATA:
            memory["ppr_history"] = memory["ppr_history"][-5:]
            memory["osm_history"] = memory["osm_history"][-5:]
            trader_data = json.dumps(memory)
            logger.log(f"[STATE TRIM] traderData trimmed to {len(trader_data)} chars")

        logger.flush()
        return result, 0, trader_data
