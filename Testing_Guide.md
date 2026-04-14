# 测试指南

> **[2026-04-14 v5.4 更新]** 回测器 fill prob 已大幅降低（0.3→0.03），PnL 基准值已更新。
> `OSM_FV` 改为动态计算，Module 2/3 的 print 语句已移除。所有通过标准已对应更新。

## 1. 基础烟雾测试（每次改动后必做）

```sh
# 单天快速验证（结果输出到当前目录）
python backtester.py "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_0.csv"

# 带报告目录
python backtester.py "d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_0.csv" \
  --output-dir "d:/IMC Prosperity 4/Backtest_Reports/Round1/<run_name>/day_0"

# 云端平台提交验证（若 prosperity4btx 工具可用）
prosperity4btx round1_trader.py 0
```

**通过标准（v5.4）**：
- 无异常或 traceback
- **Print 日志变化**：v5.4 移除了 Module 2/3 的常规 print；正常运行下仅有成交明细（`BUY/SELL ... @ ...`）和摘要行
- Final PnL > 0
- 沙盒日志中无 "exceeded limit" 警告

**返回值检查**：
- `run()` 返回类型为 `(dict[Symbol, list[Order]], int, str)`
- `traderData` 为合法 JSON，包含 `ppr_history` 和 `osm_history` 两个键
- 仅从 `datamodel` 导入（平台提供）

---

## 2. 三天全量回测（Round 1 验证）

**目标**：确认三天数据上均能盈利，且无崩溃。

```sh
DATA="d:/IMC Prosperity 4/Data/Round1/ROUND_1"
OUT="d:/IMC Prosperity 4/Backtest_Reports/Round1/<run_name>"

python backtester.py "$DATA/prices_round_1_day_-2.csv" --output-dir "$OUT/day_-2"
python backtester.py "$DATA/prices_round_1_day_-1.csv" --output-dir "$OUT/day_-1"
python backtester.py "$DATA/prices_round_1_day_0.csv"  --output-dir "$OUT/day_0"
```

**通过标准（V3 引擎，seed=42，v5.4 校准后基准）**：

| Day | 成交 ticks | PnL 目标 |
|-----|-----------|---------|
| Day -2 | ~1400 / 10000 | > +10,000 |
| Day -1 | ~1400 / 10000 | > +10,000 |
| Day  0 | ~1400 / 10000 | > +10,000 |

> 注：fill prob 降低后成交 ticks 从 ~7000 降至 ~1400，属预期行为。
> v5.4 基准：Day-2=+13,022，Day-1=+13,636，Day0=+13,554，3日合计=+40,212

**产品配置验证**：
1. `TRADING_CONFIG` 包含 `ASH_COATED_OSMIUM`（limit=80）和 `INTARIAN_PEPPER_ROOT`（limit=80）
2. `OSM_FV=10000` 作为兜底值；正常运行时 `osm_fv` 由慢 EMA + microprice 计算
3. traderData JSON 中 `osm_history` 和 `ppr_history` 均存在且长度 ≤ 20

---

## 3. 关键防护机制验证

### 场景 A：盘口非穿越钳制（防止 MM 成为 Taker）

**构造条件（v5.4 指数偏斜版）**：ASH_COATED_OSMIUM，pos=+80，best_bid=9993，best_ask=10011，FV=10000

**Phase 2 推演**：
- `compute_skew(80, 0.1, 80)` → excess=20, exp(2×20/80)=exp(0.5)≈1.65 → `skew = int(0.1×80×1.65) = 13`
- 但 pos≥70（one_side_thresh=70）→ `buy_cap=0`（单边压制，不挂买单）
- `mm_ask = 10000+1-13 = 9988`，非穿越钳制：`mm_ask = max(9988, 9993+1) = 9994`
- 最终：**无买单**，卖挂 15 手 @ 9994（price improvement，3% fill）

**验证方法**：在 pos≥70 的 tick，观察日志中仅有 `SELL` 成交，无 `BUY` 成交

### 场景 B：MAX_MM_LOT + 单边压制（pos=-70）

**构造条件**：pos=-70，limit=80

- `one_side_thresh = int(0.875 × 80) = 70`，`sim_pos = -70 ≤ -70` → `sell_cap=0`（单边压制，不挂卖单）
- `buy_cap = min(80 - (-70), 15) = 15`（仍受 MAX_MM_LOT 限制）
- 最终：买挂 15 手，**无卖单**

**验证方法**：深度持空时日志仅有 `BUY` 成交

### 场景 C：Phase 1 不受单边压制影响（Patch 3 验证）

**目标**：确认即使 pos=75，如果盘面出现 ask < FV，仍能主动买入（平仓方向）

**验证方法**：搜索 ASH_COATED_OSMIUM ask < osm_fv 的 tick，若 pos < 0，回测日志应出现 BUY（Phase 1 Taker），而非完全静默

---

## 4. 状态持久化验证（双历史 EMA）

**目标**：确认 `osm_history` 和 `ppr_history` 均正确跨 tick 传递。

**验证方法**（在 backtester 末尾临时添加）：

```python
# 在 run_backtest 最后 print 一次 trader_data 内容
import json
print(json.loads(trader_data))
# 预期输出：{'ppr_history': [...], 'osm_history': [...]}，各最多 20 个元素
```

**通过标准**：
- 两个 key 均存在
- `osm_history` 值全部在 [9950, 10050] 范围内（OSM std≈5）
- `ppr_history` 值随天数递增（Day-2≈10500，Day-1≈11500，Day0≈12500）

---

## 5. MTM 前向填充验证（Backtester v5.4）

**目标**：确认修复后 PnL 曲线无垂直跳变尖刺。

**验证方法**：查看生成的 `pnl_chart.png`

**通过标准**：PnL 曲线连续平滑，无单 tick 内绝对变化 > `max_position × max_price_spread`（约 80 × 50 = 4000）的跳变

---

## 6. 激进吃单触发验证

**目标**：确认 Phase 1 在价格偏离 FV 时正确触发主动吃单。

```sh
python - <<'EOF'
import csv
with open("d:/IMC Prosperity 4/Data/Round1/ROUND_1/prices_round_1_day_0.csv") as f:
    for row in csv.DictReader(f, delimiter=';'):
        if row['product'].strip() == 'ASH_COATED_OSMIUM':
            ask1 = row.get('ask_price_1','').strip()
            if ask1 and float(ask1) < 10000:
                print(f"ts={row['timestamp']} ask1={ask1}")
EOF
```

**通过标准**：若存在 ask < FV 的 tick，回测日志中应出现对应的 `BUY ASH_COATED_OSMIUM @ XXXX x N` 成交记录