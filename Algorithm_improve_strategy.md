# Algorithm Improve Strategy

---

## Round 0: Tutorial Round

### 市场概况

> 动态记录区域 -- 随比赛进程持续更新

**[2026-04-09] 初始观察**

产品：EMERALDS, TOMATOES
仓位上限：+/-80

| 产品 | 典型 best_bid | 典型 best_ask | 典型 spread | mid_price 特征 |
|------|-------------|-------------|------------|---------------|
| EMERALDS | 9992 | 10008 | 16 | 全天钉在 10000，几乎不动 |
| TOMATOES | ~5000 | ~5013 | 13-14 | 小幅波动（5003-5010 范围） |

- 最小 spread：EMERALDS=8，TOMATOES=6，永远不出现 spread<=2
- 市场无明显趋势，无突发事件
- 每天约 1000 笔交易，平均每笔 3-4 手

**[2026-04-12] 关键结论**

- 这是一个"平价无风险"市场：mid_price 不漂移，持仓无方向性风险
- 最优策略 = 尽可能贴近 spread 内侧报价，抢队列优先级
- Inventory skew 在此环境下无正收益（详见 Alpha Tuning 实验）

---

### 当前算法状态（v4 — 多资产配置化安全做市框架）

**更新日期**：2026-04-13

#### 架构概述

算法已从"单资产硬编码被动做市"进化为"多资产配置化安全做市框架"：

1. **统一配置字典 `TRADING_CONFIG`**：每个资产拥有独立的 `limit`（仓位上限）、`alpha`（库存偏移系数）、`base_spread`（预留参数）。新增资产只需在字典中添加一行，无需改动任何交易逻辑。

2. **仓位安全熔断 `clamp_order_volume()`**：所有订单在创建前必须通过硬性截断检查。系统保证在任何情况下，挂出的订单量都不会导致仓位超出 `[-limit, +limit]` 范围。这是绝对的安全保障——即使策略逻辑出错、参数配置异常，也不会产生违规订单。

3. **确定性日志**：每次截断或丢弃订单均输出格式化日志（`CLAMP BUY/SELL` 或 `CLAMP DROP BUY/SELL`），为后续本地回测和 debug 提供完整的可观测性。

#### 策略核心（不变）

- 竞争报价：spread > 1 时进入 spread 内部（best_bid+1 / best_ask-1）
- 库存偏移：`skew = int(alpha * position)`，对称偏移买卖报价
- 2 层报价：Layer 1（激进，紧报价）+ Layer 2（被动，宽报价）
- 交叉保护：`my_bid >= my_ask` 时退回原始市场价格

#### 已配置资产

| 资产 | limit | alpha | base_spread | 备注 |
|------|-------|-------|-------------|------|
| EMERALDS | 80 | 0.1 | 1 | Tutorial Round 主力 |
| TOMATOES | 80 | 0.1 | 1 | Tutorial Round 主力 |
| AMETHYSTS | 20 | 0.05 | 2 | R1 预留 |
| STARFISH | 20 | 0.5 | 4 | R1 预留 |

---

### 算法版本记录

#### v1 -- Skeleton (2026-04-09)

**构成**：平台合规的 Trader 类骨架，简单市价单
**表现**：未实测（骨架阶段）

#### v2 -- Basic Market Making (2026-04-09)

**构成**：买挂单 @ best_bid，卖挂单 @ best_ask
**表现**：未实测（代码审查通过）

#### v2.5 -- Competitive Market Making (2026-04-09)

**构成**：spread > 1 时进入内部报价，交叉保护
**表现**：PNL = 621（基准值）

#### v3 -- Reservation Price + 2-Layer Quoting (2026-04-12)

**构成**：竞争报价 + inventory skew + 2 层报价
**表现**：Alpha Tuning 实验证明 alpha=0 在此市场最优（PNL=621），alpha 越大 PNL 越低

#### v4 -- Multi-asset Config & Hard Limits (2026-04-13)

**构成**：v3 逻辑不变 + `TRADING_CONFIG` 统一配置 + `clamp_order_volume()` 硬性熔断
**特点**：
- 纯框架升级，不改变策略行为
- 绝对仓位安全保障
- 为 R1 多资产部署做好结构准备
**表现**：待回测验证（预期 PNL 不变）

---

### 对后续 Round 的启示

1. **Inventory skew 不是无用，是在此环境无用**。后续 round 如果 mid_price 有趋势或高波动，inventory skew 将成为必要的风险管理工具。
2. **alpha 调参需配合 int() 截断效应**。如果继续使用 `int(alpha * position)` 结构，需要确保 alpha 大到足以在典型仓位下产生 >= 1 的 skew。
3. **市场微结构决定策略上限**。在给定 spread 和成交频率下，做市收益存在硬顶。突破需要新的策略维度（如趋势跟踪、跨品种对冲）。
4. **新增资产零成本接入**。只需在 `TRADING_CONFIG` 中添加一行配置，无需修改任何交易逻辑代码。

---

## Round 1

### 市场概况

> 动态记录区域 -- 随比赛进程持续更新

**[2026-04-14] 初始观察（基于官方下载数据 Day -2, -1, 0）**

产品：ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT
仓位上限：+/-80

| 产品 | 典型 best_bid | 典型 best_ask | 典型 spread | mid_price 特征 |
|------|-------------|-------------|------------|---------------|
| ASH_COATED_OSMIUM | ~9993-9998 | ~10007-10013 | 14-20 | 三天均值≈10000，std≈5，高度稳定 |
| INTARIAN_PEPPER_ROOT | 变动大 | 变动大 | ~14-16 | 每天上涨+1000（Day-2:≈10500，Day-1:≈11500，Day0:≈12500） |

**价格范围（非零 mid_price，三天实测）**：

| 产品 | Day -2 | Day -1 | Day 0 |
|------|--------|--------|-------|
| ASH_COATED_OSMIUM | 9979-10019，mean=9998 | 9982-10019，mean=10001 | 9977-10023，mean=10002 |
| INTARIAN_PEPPER_ROOT | 9998-11003，mean=10500 | 10995-12006，mean=11500 | 11994-13007，mean=12500 |

关键发现：
- ASH_COATED_OSMIUM 是 Round1 的 **固定公允价值资产**，FV=10000（对标 Tutorial Round EMERALDS）
- INTARIAN_PEPPER_ROOT 是 Round1 的 **趋势资产**，每天线性上涨约 +1000（对标 Tutorial Round TOMATOES）
- 单侧空盘（empty book 一侧）情况存在，mid_price=0 数据点需过滤
- 最小 tick spread 约 14-20，远大于 Tutorial Round（spread≈2），做市收益空间更大

---

### 当前算法状态（v8.0b — OSM 双层 Maker + PPR Drift 最大化）

**更新日期**：2026-04-17

#### 架构概述

v8.0b 在 v8.0 基础上为 OSM 新增双层 Maker 挂单（结构性改动），PPR 保持不变。v8.1 证实简单参数调优无效，转向结构性改动。

1. **PPR 仓位最大化策略**（同 v8.0，不变）：
   - FV = 0.3 x 快速EMA(alpha=0.6) + 0.7 x microprice + DRIFT_BIAS(10)
   - 永久 TREND_UP：禁止所有卖出（Phase 1b + Phase 2 sell）
   - taker_alpha=0.0：无建仓惩罚，pos=+50 时买入阈值不衰减
   - unwind_thresh=None：不减仓，持多到底

2. **OSM 双层 Maker 做市**（v8.0b 新增 Layer 2）：
   - Layer 1（不变）：FV ± eff_spread - skew，手数 = MAX_MM_LOT(20)
   - Layer 2（新增）：FV ± (eff_spread + OSM_L2_OFFSET(4)) - skew，手数 = OSM_L2_LOT(10)
   - L2 引入条件：layer2_offset > 0 and layer2_lot > 0
   - L2 共享 L1 所有安全机制：非穿越钳制、one-side 阈值、OBI 过滤
   - L2 更深在盘口，捕捉波动尖峰成交；Module 4 仓位钳制保证总订单不超限
   - PPR 不使用 Layer 2（defaults layer2_offset=0, layer2_lot=0）
   - Kalman/AS 参数同 v8.0：Q=0.015, AS_GAMMA=2.0, MAX_MM_LOT=20

3. **安全架构不变**：Module 4 仓位钳制、指数偏斜、盘口非穿越钳制全部保留

#### 核心公式

**非线性指数偏斜** `compute_skew(pos, alpha=0.1, limit=80, k=2.0, threshold=0.75)`：
```
threshold = 0.75 × limit = 60
线性区 (|pos| < 60):  skew = int(alpha × |pos|)
指数区 (|pos| ≥ 60):  skew = int(alpha × |pos| × exp(k × (|pos| - 60) / limit))

pos=40 → 4  |  pos=60 → 6  |  pos=70 → 8  |  pos=78 → 12
```

**OSM 动态 FV（v6.0+: Kalman Filter）**：
```
kalman_update_1d(x, P, z, Q=0.015, R=4.0)
K_steady ~ sqrt(Q/R) ~ 0.061
osm_fv = kalman_x（自适应追踪，冷启动 K0 ~ 0.86 快速收敛）
```

**PPR 动态 FV（v8.0: Drift Bias）**：
```
ema = EMA(ppr_history, alpha=0.6)      # 快速 EMA，半衰期 ~1.2 tick
dynamic_fv = 0.3 * ema + 0.7 * microprice + 10   # DRIFT_BIAS = 10
```

#### 已配置资产

| 资产 | limit | alpha | FV策略 | 备注 |
|------|-------|-------|--------|------|
| ASH_COATED_OSMIUM | 80 | 0.1 | Kalman(Q=0.015,R=4.0) | 均值回归做市，AS_GAMMA=2.0 |
| INTARIAN_PEPPER_ROOT | 80 | 0.1 | 快速EMA+micro+drift_bias(10) | 仓位最大化，永久 TREND_UP |

---

### 算法版本记录

#### v1 -- Skeleton (2026-04-09)
**构成**：平台合规骨架 | **表现**：未实测

#### v2 -- Basic Market Making (2026-04-09)
**构成**：挂单 @ best_bid/ask | **表现**：未实测

#### v2.5 -- Competitive Market Making (2026-04-09)
**构成**：spread > 1 时进入内部报价 | **表现**：Tutorial PNL = 621

#### v3 -- Reservation Price + 2-Layer Quoting (2026-04-12)
**构成**：竞争报价 + inventory skew + 2 层报价 | **表现**：Alpha Tuning 证明 alpha=0 最优（Tutorial PNL=621）

#### v4 -- Multi-asset Config & Hard Limits (2026-04-13)
**构成**：v3 逻辑 + `TRADING_CONFIG` 统一配置 + `clamp_order_volume()` 熔断 | **表现**：框架升级，PNL 不变（Tutorial 验证待测）

#### v5 -- Round 1 AggressiveTaker + EMA FV + Guarded MM (2026-04-14)

**构成**：激进吃单（Taker 100%）+ EMA 动态FV(PPR) + 线性库存偏斜做市 + 盘口非穿越钳制 + MAX_MM_LOT=15

**表现**（V3 随机撮合引擎，random.seed=42，`FILL_PROB_IMPROVEMENT=0.3`）：

| Day | 成交 ticks | Final PnL |
|-----|-----------|-----------|
| Day -2 | 7127 / 10000 | **+66,013.50** |
| Day -1 | 7180 / 10000 | **+77,964.00** |
| Day  0 | 7218 / 10000 | **+60,143.00** |
| **3日合计** | | **+204,120.50** |

注：回测 PnL 虚高（本地 66k vs 云端 2508），因 fill prob 过高且 MTM 存在估值尖刺。

#### v5.4 -- Dynamic OSM FV + Non-linear Skew + Backtester Calibration (2026-04-14)

**构成**：
- **回测器校准**：FILL_PROB 0.3→0.03 / 0.1→0.02；MTM 前向填充防估值尖刺
- **OSM 动态 FV**：慢EMA(alpha=0.05) × 0.8 + microprice × 0.2；冷启动坚守 10000
- **指数偏斜**：`compute_skew()` 在 pos≥60 时指数放大，pos≥70 时单边压制（仅 Maker 层）
- **状态持久化**：`osm_history` + `ppr_history` 共同存入 traderData JSON
- 移除冗余 print，防云端日志超限

**表现**（V3 随机撮合引擎，random.seed=42，`FILL_PROB_IMPROVEMENT=0.03`）：

| Day | 成交 ticks | Final PnL | OSM 末仓 | PPR 末仓 |
|-----|-----------|-----------|---------|---------|
| Day -2 | 1419 / 10000 | **+13,022.00** | +47 | +75 |
| Day -1 | 1437 / 10000 | **+13,636.00** | +27 | -71 |
| Day  0 | 1428 / 10000 | **+13,554.00** | -42 | -33 |
| **3日合计** | | **+40,212.00** | — | — |

关键观察：
- OSM 末仓不再钉在 +/-80，说明动态 FV + 指数偏斜有效驱动库存回归
- 本地/云端比率约 5x（13k/2.5k），剩余差距来自云端对手盘逆向选择和延迟

#### v6.0 -- Kalman FV + Position-Aware Phase 1 + AS Dynamic Spread (2026-04-15)

**构成**：
- OSM FV: EMA混合 to 1D Kalman(Q=0.005, R=4.0, P0=25)
- Phase 1 仓位感知阈值：OSM_TAKER_ALPHA=0.1
- Phase 2 AS 动态点差：OSM_AS_GAMMA=2.0, PPR_AS_GAMMA=0.15

**表现**：云端 **3,352 XIREC / 100K ticks**（v5.8 基线 2,441，+37.3%）

#### v7.0 -- Active Unwind + Regime Switching + OBI (2026-04-16)

**构成**：
- OSM/PPR Active Unwind: |pos|>=70 时 Phase 1c 强制减仓 5 手/tick
- PPR Regime Switching: 20-tick 线性回归斜率 + 3-tick 确认
- PPR_TAKER_ALPHA=0.1（与 OSM 对称）
- OBI 对冲选择过滤（Phase 2 only）

**表现**：云端 **4,597 XIREC / 100K ticks**（v6.0 基线 3,352，+37.1%）
- OSM=1,683, PPR=2,914
- PPR bottleneck: 16 trades, 50/80 position, 57% idle time

#### v8.0 -- PPR Drift Maximization + OSM Capacity Upgrade (2026-04-17)

**构成**：
- PPR FV = 0.3 x EMA(alpha=0.6) + 0.7 x micro + DRIFT_BIAS(10)
- PPR permanent TREND_UP (skip_dir=1, no sells ever)
- PPR_TAKER_ALPHA=0.0, unwind_thresh=None
- OSM_KALMAN_Q: 0.005 to 0.015
- MAX_MM_LOT: 15 to 20, OSM_UNWIND_LOT: 5 to 10

**预期**：云端 8,000-10,000 XIREC / 100K ticks（v7.0 基线 4,597，~2x）
**表现**：云端 **9,028 XIREC / 100K ticks**（v7.0 基线 4,597，+96.3%）Submission ID 247252
- PnL 曲线近乎完美线性（drift 收入主导）
- Projected final scoring (10K iter): ~88,500 XIREC (best estimate), R1 target completion ~73.8%

#### v8.1 -- OSM Parameter Tuning + PPR Entry Cost Reduction (2026-04-17)

**构成**：
- OSM_AS_GAMMA: 2.0 to 1.4（报价宽度 ~10→~7）
- OSM_KALMAN_Q: 0.015 to 0.025（K: 0.061→0.079）
- OSM_UNWIND_THRESH: 70 to 60（更早减仓）
- OSM_TAKER_ALPHA: 0.1 to 0.05（减半仓位惩罚）
- MAX_MM_LOT: 20 to 25（利用盘口深度）
- PPR_DRIFT_BIAS: 10 to 7（节省 ~240 建仓成本）

**预期**：云端 10,000-11,000 XIREC / 100K ticks（v8.0 基线 9,028，+10-20%）
**表现**：云端 **8,774 XIREC**（v8.0 基线 9,028，-2.8%）—— **回滚至 v8.0**
- AS_GAMMA 1.4 缩小报价宽度可能增加了逆向选择风险，抵消了成交率提升的收益

#### v8.0b -- OSM Dual-Layer Maker (2026-04-17)

**构成**：
- 新增 OSM Layer 2 做市挂单：FV ± (eff_spread + 4) - skew，手数 = 10
- Layer 1 完全不变：FV ± eff_spread - skew，手数 = MAX_MM_LOT(20)
- 所有 v8.0 参数保持不变（AS_GAMMA=2.0, KALMAN_Q=0.015, MAX_MM_LOT=20 等）
- PPR 不使用 Layer 2（layer2_offset/layer2_lot defaults to 0）
- L2 共享 L1 安全机制：非穿越钳制、one-side 阈值、OBI 过滤、Module 4 仓位钳制

**预期**：云端 9,200-9,800 XIREC / 100K ticks（v8.0 基线 9,028，+2-8%）
**表现**：云端 **9,028 XIREC**（与 v8.0 完全一致）Submission ID 252480 —— **回滚至 v8.0**
- Layer 2 报价在 FV ± ~12，深于典型 best bid/ask（~9992/~10008），低波动市场 0 成交

---

### 对后续优化的启示

1. **PPR 已达理论极限**。247252.log 证实：993/999 ticks 精确 +8.0 XIREC/tick，0 idle。后续 PPR 优化空间为 0。
2. **OSM 是唯一杠杆，但简单参数调优无效**。v8.1 尝试缩小 AS_GAMMA/加快 Kalman/提前 unwind，结果 PnL -2.8%。更紧报价增加了逆向选择风险。
3. **OSM 结构性改动也无效**。v8.0b 双层 Maker 挂单（L2 +4 点偏移）在低波动市场中 0 成交。OSM 1,688 可能已接近此数据集天花板。
4. **运行间方差显著**。同一算法两次提交：9,828 vs 9,028（差 8.6%）。单次测试的 PnL 差异可能被误判为策略改进/退化。
