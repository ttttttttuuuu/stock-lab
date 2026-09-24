# 美股周期权自动交易系统（纸面交易阶段）

每周到期的美股期权短线系统：免费数据 → 多策略回测 → 每日信号 → Next.js 看板。
**当前不接真实交易**（富途接口已预留 stub）。

## 架构

```
┌─────────────────────────────────────────────────────────┐
│ 数据层  engine/nasdaq.py                                 │
│   · Nasdaq 公开 API（免 key）：日线 OHLCV + 期权链        │
│   · 缓存到 data/cache/，每日自动刷新                       │
├─────────────────────────────────────────────────────────┤
│ 策略层  engine/indicators.py + strategies.py             │
│   · SMA 10/30 交叉（趋势）                                │
│   · RSI(14) 均值回归                                     │
│   · MACD 柱状线趋势                                      │
│   · 布林带突破                                           │
│   · Ensemble：以上 4 策略多数投票（≥2 票同向才行动）        │
├─────────────────────────────────────────────────────────┤
│ 回测层  engine/backtest.py + options_sim.py              │
│   · 每笔 $100 买入 ~7 天到期 ATM 周期权（Call/Put）        │
│   · 期权历史价不免费 → Black-Scholes 模拟                 │
│     （标的价 + 20 日历史波动率作 IV 代理 + 4.5% 无风险利率）│
│   · 出场：信号翻转 / 止损 -50% / 止盈 +100% / 5 交易日限时  │
├─────────────────────────────────────────────────────────┤
│ 存储层  engine/storage.py                                │
│   · 本地 SQLite：data/trader.db（默认，开箱即用）           │
│   · Supabase：配置 .env 后自动同步（supabase/schema.sql）  │
├─────────────────────────────────────────────────────────┤
│ 展示层  web/（Next.js 15 + Recharts）                    │
│   · /        总览：排行榜 + 净值曲线 + 标的×策略热力图      │
│   · /trades  全部交易明细（可筛选/分页）                   │
│   · /signals 每日信号矩阵 + 纸面持仓                      │
├─────────────────────────────────────────────────────────┤
│ 自动化  Blueprint 定时任务                                │
│   · cron "40 5 * * 2-6"（Asia/Shanghai）= 美股收盘后       │
│   · 刷新数据 → 计算信号 → 纸面开平仓 → 导出前端 JSON       │
└─────────────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 1. 回测（2 年，10 只标的 × 5 策略）
python3 -m engine.run_backtest --years 2

# 2. 每日信号 + 纸面交易（定时任务已配置，也可手动跑）
python3 -m engine.daily_signals

# 3. 导出前端数据
python3 -m engine.export_web

# 4. 启动看板
cd web && npm install && npm run dev
```

## 接入 Supabase（可选）

1. 在 Supabase 建项目，SQL 编辑器执行 `supabase/schema.sql`
2. `cp .env.example .env`，填入 `SUPABASE_URL` / `SUPABASE_SERVICE_KEY`
   → 之后每次回测/每日任务结束自动同步全部表（含纸面持仓）
3. `cp web/.env.example web/.env.local`，填入 `NEXT_PUBLIC_SUPABASE_URL` /
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` → 看板切换为读云端（导航栏右上角显示
   当前数据源：Local SQLite / ☁ Supabase）

## 交易规则（重要假设）

- 每笔固定 **$100** 权利金；模拟允许碎股合约（qty = 100 / (premium × 100)），
  实盘中 $100 预算只能买极低价合约，建议届时调整为每笔 1 张、预算上限 $500
- 信号在日收盘产生并同价成交（close-to-close 近似）
- IV 用 20 日历史波动率代理，与实际期权链 IV 有偏差 →
  **回测盈亏用于策略间相对比较，不代表真实收益**

## 数据源说明

- Yahoo Finance 在本机网络不可达；Stooq 有 JS 验证墙
- 采用 Nasdaq 官方公开 API（无需 key）：日线历史 + 完整期权链
- **纸面交易已使用真实期权链报价**：选约取距 7 天最近到期、最靠近平值的合约，
  开仓按 ask（或买卖中价/最新成交价），平仓按 bid 标记；BS 仅在链不可用时兜底
- 回测仍用 BS 模拟（期权历史成交价无免费源），用于策略间相对比较

## 富途真实交易（路线图，暂未启用）

见 `engine/broker_futu.py`：需本地 OpenD 网关 + `futu-api`，
先用 `TrdEnv.SIMULATE` 仿真环境，接口契约已固定，引擎无需改动。
