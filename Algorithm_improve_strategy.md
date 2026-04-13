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
