"""
round1_trader.py — IMC Prosperity 4 Round 1 策略  [v6.0]
=========================================================
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
# CHANGELOG v6.0（相对 v5.8）— 三层升级
# 改动 1: OSM FV: EMA混合 → 1D Kalman(Q=0.005, R=4.0, P₀=25)
#   · 冷启动K₀≈0.86（立即收敛），稳态K≈0.034（7×慢于EMA有效α=0.24）
#   · 彻底消除开盘30tick"热机死区"
# 改动 2: Phase 1 仓位感知阈值（仅OSM，OSM_TAKER_ALPHA=0.1）
#   · 买入阈值: fv - int(0.1 * max(sim_pos, 0))；pos=+80时需ask<fv-8
#   · 根治OSM长仓饱和（目标：596 ticks→<150 ticks）
# 改动 3: Phase 2 AS动态点差（双资产）
#   · δ_raw = max(1, round(γ×σ_micro))；book_half上限防止出市报价
#   · OSM: γ=2.0 + book_half=1上限 → δ恒为1（零副作用）
#   · PPR: γ=0.15 + 宽买卖差 → σ≥10时δ→2，每笔成交收益翻倍
# 云端目标: ≥3200 XIREC/100K ticks（基线2441）
# ================================================================
# CHANGELOG v5.8（相对 v5.4）— 完整回滚至 v5.4 参数基线
# 回滚原因:
#   v5.6 (Change 4: OSM_MICRO_WEIGHT 0.45→0.25) 云端 PnL ≈2205，低于 v5.4 的 2441
#   v5.7 (Path B: Phase 1 gate ±40) 云端 PnL ≈2205，同样低于 v5.4
#   v5.6 和 v5.7 均在 v5.5 参数基础上改动，无法突破 v5.5 造成的性能上限
#   根因：v5.5 引入的三个参数（OSM_MICRO_WEIGHT 0.20→0.45, SKEW_K 2.0→3.0,
#         SKEW_THRESHOLD 0.75→0.60）使云端 PnL 从 2441 下降至 ~2205
# 本次回滚内容:
#   OSM_MICRO_WEIGHT : 0.45 → 0.20  （v5.4 原始值）
#   SKEW_K           : 3.0  → 2.0   （v5.4 原始值）
#   SKEW_THRESHOLD   : 0.60 → 0.75  （v5.4 原始值）
#   Phase 1 gate (v5.7) 完全移除
# 保留不变（v5.4 已有架构）:
#   动态 OSM FV（慢EMA + microprice 混合）
#   osm_history 状态持久化
#   fv_int = round(fv) 取整修复
#   microprice 参数（无害，不影响逻辑）
#   DIAG_MODE = False（云端安全）
# ================================================================
# CHANGELOG v5.7（相对 v5.5）— Path B: OSM Phase 1 双向仓位门控 — REVERTED
# 新增参数 (已移除):
#   taker_buy_gate  = +40
#   taker_sell_gate = -40
# 云端结果: PnL = 2205（与 v5.6 相同，低于 v5.4 基准 2441）→ CLOSED
# ================================================================
# CHANGELOG v5.6（相对 v5.5）— Change 4 batch — REVERTED
# 试验参数:
#   OSM_MICRO_WEIGHT : 0.45 → 0.25  （已回滚回 0.45）
# 测试结论:
#   0.25 权重令 FV 对上行脉冲不敏感 → Phase 1 卖单大量触发 → 短侧饱和
#   Day -1 OSM ≤-70：20 → 554 tick (+27倍)；短侧饱和比原始问题更严重
#   OSM 总 MTM PnL 仅从 +36 微升至 +130，改善可忽略
#   长侧饱和改善(≥+80: -39%)但短侧同等恶化(≤-70: +131%)，参数影响对称
#   → OSM_MICRO_WEIGHT 是对称参数，无法单独修复单侧饱和
# 下一步方向:
#   Path A: 试验中间值 OSM_MICRO_WEIGHT=0.35（温和调低）
#   Path B: 增加 OSM Phase 1 仓位门控（±40 硬盖），直接限制吃单深度
#   DIAG_MODE 仍保持 False（云端安全状态）
# ================================================================
# CHANGELOG v5.5（相对 v5.4）
# 参数变动对照表:
#   OSM_MICRO_WEIGHT : 0.20 → 0.45  更激进的微价格权重，早捕均值回归
#   SKEW_THRESHOLD   : 0.75 → 0.60  指数惩罚门槛提前，减少中等仓位积累
#   SKEW_K           : 2.0  → 3.0   极端仓位惩罚更陡，加速去化
#   JUMP_THRESHOLD   : 新增 15      microprice 偏离 FV > 15 时扩大 spread
# 逻辑增强:
#   compute_skew()         : exp 指数加 min(..., 20) 安全钳制，防未来参数引发溢出
#   aggressive_take_and_mm(): fv_int=int(round(fv)) 消除取整偏误
#   aggressive_take_and_mm(): 新增 microprice 参数 + 双向跳变过滤
#   PPR 调用处             : 不传 microprice（默认 None），不触发跳变过滤
#   序列化                 : osm/ppr_history 严格裁剪至 MAX_HISTORY=20
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
OSM_MICRO_WEIGHT = 0.20      # v5.8: 回滚至v5.4原始值（20%）; v5.5升至0.45后云端PnL从2441降至~2205
OSM_MIN_HISTORY  = 3         # v5.4: EMA预热最小历史点数

# --- v6.0: Kalman filter for OSM FV (replaces EMA blend) ---
OSM_KALMAN_Q  = 0.005        # process noise variance (mean-rev asset drifts ~0.07/tick)
OSM_KALMAN_R  = 4.0          # observation noise variance (microprice σ≈2 from microstructure)
OSM_KALMAN_P0 = 25.0         # initial error covariance (σ=5 for OSM → P₀=σ²=25)

# --- v6.0: Position-aware Phase 1 taker threshold (OSM only) ---
OSM_TAKER_ALPHA = 0.1        # inventory penalty on Phase 1 threshold
                              # pos=+40 → buy only asks < fv-4; pos=+80 → buy only asks < fv-8

# --- v6.0: Avellaneda-Stoikov dynamic spread for Phase 2 ---
OSM_AS_GAMMA    = 2.0        # OSM gamma (tight book → book_half cap keeps δ=1 for OSM)
PPR_AS_GAMMA    = 0.15       # PPR gamma (wide book → δ→2 when σ_tick≥10)
AS_VOL_LOOKBACK = 10         # rolling window for micro-vol estimation (ticks)

# --- INTARIAN_PEPPER_ROOT：趋势资产 ---
# 三天数据验证：每天上涨+1000，std≈288，需 EMA 追踪趋势
PPR_LIMIT = 80
PPR_ALPHA = 0.1
EMA_ALPHA    = 0.2           # EMA 平滑因子，等效约 9 期
MICRO_WEIGHT = 0.3           # 微观价格对最终动态FV的修正权重（30%）
MAX_HISTORY  = 20            # 最多保留的历史价格点数
MIN_HISTORY  = 3             # 历史点数不足时退化为纯微观价格
MAX_MM_LOT   = 15            # 单笔 MM 被动挂单上限（防止单次成交从极端到极端）

# --- v5.5: 非线性指数库存偏斜参数 ---
SKEW_K         = 2.0         # v5.8: 回滚至v5.4原始值（v5.5曾改为3.0）
SKEW_THRESHOLD = 0.75        # v5.8: 回滚至v5.4原始值（v5.5曾改为0.60）
ONE_SIDE_FRAC  = 0.875       # 单边报价阈值（仓位 >= 87.5% * limit，即70/80）

# --- v5.5: 价格跳变过滤阈值 ---
JUMP_THRESHOLD = 15          # microprice 与 FV 偏离超过 15 units 判定为异常跳变

# --- 诊断模式（本地回测用，云端保持 False）---
DIAG_MODE = False            # Set True locally to emit Diagnostic 2 & 4 prints; False for cloud submission

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
        exponent = min(k * excess / limit, 20.0)   # v5.5: 安全钳制，防未来大参数引发溢出
        raw = linear_part * math.exp(exponent)
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


def kalman_update_1d(
    x: float, P: float, z: float,
    Q: float = OSM_KALMAN_Q,
    R: float = OSM_KALMAN_R,
) -> tuple[float, float]:
    """
    1D Kalman filter — predict + update (F=1, H=1, no control input).

    State model:   x_t = x_{t-1} + w,  w ~ N(0, Q)   (slow random-walk drift)
    Observation:   z_t = x_t + v,       v ~ N(0, R)   (noisy microprice)

    Steady-state gain K ≈ 0.034 for Q=0.005, R=4.0 (7× slower than EMA α=0.24).
    Cold-start gain K₀ ≈ P₀/(P₀+R) = 25/29 ≈ 0.86 — snaps to first obs quickly.
    """
    P_pred = P + Q                      # predict: uncertainty grows by Q each tick
    K      = P_pred / (P_pred + R)      # Kalman gain
    x_new  = x + K * (z - x)           # posterior state estimate
    P_new  = (1.0 - K) * P_pred        # posterior covariance
    return x_new, P_new


def compute_micro_vol(prices: list, lookback: int = AS_VOL_LOOKBACK) -> float:
    """
    Rolling standard deviation of recent micro-price changes.

    Used by the Avellaneda-Stoikov dynamic spread: δ = max(1, round(γ × σ)).
    Returns 0.0 if fewer than 2 price points available.
    """
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
    microprice: float | None = None,        # v5.5: 用于价格跳变过滤；PPR 调用处不传，默认 None
    taker_alpha: float = 0.0,               # v6.0: position-aware Phase 1 penalty (0 = disabled)
    half_spread: int   = 1,                 # v6.0: AS dynamic half-spread from caller
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

    # ---------- Phase 1a: 仓位感知主动买入（v6.0）----------
    # 当持多时，要求更大的价格优势才出手：threshold = fv_int - int(taker_alpha * max(pos, 0))
    # taker_alpha=0（PPR默认）时 threshold=fv_int，行为与v5.8完全相同
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

    # ---------- Phase 1b: 仓位感知主动卖出（v6.0）----------
    # 当持空时，要求更大的价格优势才出手：threshold = fv_int + int(taker_alpha * max(-pos, 0))
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
        if DIAG_MODE and symbol == "INTARIAN_PEPPER_ROOT" and sim_pos <= -30:
            print(f"[DIAG_P1] PPR p1-sell: bid={bid_price} fv={fv_int} delta={bid_price - fv_int} pos={sim_pos}")
        sim_pos -= vol

    # ---------- Phase 2: AS动态点差 + 非线性库存偏斜被动做市（v6.0）----------
    # 先取盘口（非穿越约束和AS书册上限均需要）
    best_bid_now = max(order_depth.buy_orders.keys())  if order_depth.buy_orders  else None
    best_ask_now = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

    skew = compute_skew(sim_pos, alpha, limit)

    # v6.0: book-aware AS spread — cap δ by current book half-spread
    # OSM tight book (spread=2) → book_half=1 → δ always capped at 1 (no change)
    # PPR wide book (spread≥4) → book_half≥2 → δ can widen to 2-3 in volatile periods
    if best_bid_now is not None and best_ask_now is not None:
        book_half  = max(1, (best_ask_now - best_bid_now) // 2)
        eff_spread = min(half_spread, book_half)
    else:
        eff_spread = half_spread

    mm_bid = fv_int - eff_spread - skew
    mm_ask = fv_int + eff_spread - skew

    # ---- 关键约束：MM 报价绝不能穿越盘口，防止被 V3 引擎识别为 Taker ----
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
        if DIAG_MODE and symbol == "INTARIAN_PEPPER_ROOT" and sim_pos <= -30:
            print(f"[DIAG_P2_POST] PPR p2-sell post: ask={mm_ask} fv={fv_int} pos={sim_pos} vol={sell_cap}")
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
        # ASH_COATED_OSMIUM 历史微观价格列表（保留用于AS动态点差的micro_vol计算）
        osm_history: list = memory.get("osm_history", [])
        # v6.0: Kalman filter state for OSM FV (replaces EMA blend)
        osm_kf_x: float = memory.get("osm_kf_x", float(OSM_FV))   # FV posterior estimate
        osm_kf_P: float = memory.get("osm_kf_P", OSM_KALMAN_P0)   # error covariance

        # ============================================================
        # Module 2: ASH_COATED_OSMIUM — Kalman FV + 仓位感知 Phase 1（v6.0）
        # FV = 1D Kalman(Q=0.005, R=4.0, P₀=25): K₀≈0.86（快速冷启动），稳态K≈0.034
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

                # --- 2b: 更新历史列表（保留，供AS动态点差的micro_vol使用）---
                if micro_osm is not None:
                    osm_history.append(micro_osm)
                    if len(osm_history) > MAX_HISTORY:
                        osm_history = osm_history[-MAX_HISTORY:]

                # --- 2c: Kalman FV更新（替代EMA混合）---
                if micro_osm is not None:
                    osm_kf_x, osm_kf_P = kalman_update_1d(
                        osm_kf_x, osm_kf_P, micro_osm, Q=OSM_KALMAN_Q, R=OSM_KALMAN_R
                    )
                osm_fv = osm_kf_x   # 后验FV估计（无观测时维持先验）

                # --- 2d: 计算AS动态点差并下单 ---
                osm_vol    = compute_micro_vol(osm_history, AS_VOL_LOOKBACK)
                osm_spread = max(1, round(OSM_AS_GAMMA * osm_vol))
                osm_orders = aggressive_take_and_mm(
                    SYM_OSM, od_osm, osm_fv, pos_osm, OSM_LIMIT, OSM_ALPHA,
                    taker_alpha=OSM_TAKER_ALPHA,
                    half_spread=osm_spread,
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

                # --- 3d: 计算AS动态点差并下单 ---
                if dynamic_fv is not None:
                    ppr_vol    = compute_micro_vol(ppr_history, AS_VOL_LOOKBACK)
                    ppr_spread = max(1, round(PPR_AS_GAMMA * ppr_vol))
                    ppr_orders = aggressive_take_and_mm(
                        SYM_PPR, od_ppr, dynamic_fv, pos_ppr, PPR_LIMIT, PPR_ALPHA,
                        taker_alpha=0.0,
                        half_spread=ppr_spread,
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
        memory["osm_history"] = osm_history   # retained for AS micro_vol computation
        memory["osm_kf_x"]    = osm_kf_x      # v6.0: Kalman FV posterior estimate
        memory["osm_kf_P"]    = osm_kf_P      # v6.0: Kalman error covariance
        trader_data = json.dumps(memory)

        return result, 0, trader_data
