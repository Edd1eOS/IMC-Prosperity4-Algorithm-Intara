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

### 当前算法状态（v5.4 — 动态OSM FV + 非线性偏斜 + 回测器校准）

**更新日期**：2026-04-14

#### 架构概述

在 v5 四模块架构基础上，完成三项关键升级：

1. **状态序列化模块**：`traderData` JSON 同时存储 `ppr_history` 和 `osm_history`（各最多 20 个 micro-price）。`try/except` 包裹保证任何解析失败不崩溃。

2. **ASH_COATED_OSMIUM（动态FV，v5.4 升级）**：
   - Phase 1 激进吃单：扫描所有 ask < FV（全额买入）和 bid > FV（全额卖出），V3 引擎 100% 成交
   - 动态 FV = `0.8 × slow_EMA(alpha=0.05) + 0.2 × microprice`；冷启动期（历史<3点）坚守 10000
   - Phase 2 非线性偏斜做市：`compute_skew()` 指数函数，pos≥60 时急剧放大偏斜，pos≥70 时单边压制

3. **INTARIAN_PEPPER_ROOT（EMA动态FV，不变）**：
   - `compute_microprice()` = (best_bid × q_ask + best_ask × q_bid) / (q_bid + q_ask)
   - `dynamic_fv = 0.7 × EMA(alpha=0.2) + 0.3 × micro`
   - Phase 2 同样使用 `compute_skew()` 和单边压制

4. **三个关键防护（v5.4）**：
   - *盘口非穿越钳制*：`mm_bid ≤ best_ask - 1`，`mm_ask ≥ best_bid + 1`
   - *MAX_MM_LOT = 15*：单笔 MM 最多 15 手
   - *单边报价压制*：`|pos| ≥ 70`（87.5% × 80）时仅挂平仓方向；**仅 Phase 2 Maker，Phase 1 Taker 不受限**

5. **双层 try/except 隔离** + **Module 4 最终头寸钳制**（绝对安全网，不可修改）

#### 核心公式

**非线性指数偏斜** `compute_skew(pos, alpha=0.1, limit=80, k=2.0, threshold=0.75)`：
```
threshold = 0.75 × limit = 60
线性区 (|pos| < 60):  skew = int(alpha × |pos|)
指数区 (|pos| ≥ 60):  skew = int(alpha × |pos| × exp(k × (|pos| - 60) / limit))

pos=40 → 4  |  pos=60 → 6  |  pos=70 → 8  |  pos=78 → 12
```

**OSM 动态 FV**：
```
slow_ema = EMA(osm_history, alpha=0.05)    # 约19期，追踪长期漂移
osm_fv   = 0.8 × slow_ema + 0.2 × microprice
冷启动（len(osm_history) < 3）: osm_fv = 10000
```

#### 已配置资产

| 资产 | limit | alpha | FV策略 | 备注 |
|------|-------|-------|--------|------|
| ASH_COATED_OSMIUM | 80 | 0.1 | 慢EMA(0.05)+micro(20%) | v5.4: 动态FV，冷启动守10000 |
| INTARIAN_PEPPER_ROOT | 80 | 0.1 | EMA(0.2)+micro(30%) | 趋势资产，不变 |

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
- OSM 末仓不再钉在 ±80，说明动态 FV + 指数偏斜有效驱动库存回归
- 本地/云端比率约 5x（13k/2.5k），剩余差距来自云端对手盘逆向选择和延迟

---

### 对后续优化的启示

1. **MAX_MM_LOT 是防止仓位震荡的关键参数**。当前 15 手是经验值，可在更多数据上调优（10-25 手范围）。
2. **EMA 追踪趋势的延迟问题**。INTARIAN_PEPPER_ROOT 每 tick 涨约 0.1，EMA(alpha=0.2) 延迟约 4 tick（0.4 单位）。延迟可接受，但如果趋势加速需要增大 alpha。
3. **ASH_COATED_OSMIUM 的激进吃单机会**。FV=10000 硬编码正确，当 ask < 10000 时抢单机会每日均有出现。
4. **PEPPER_ROOT 趋势方向性**。当前策略是中性 MM，未利用"每天必涨+1000"的确定性趋势。后续可考虑在 PPR 上偏多（持仓偏正方向）。
