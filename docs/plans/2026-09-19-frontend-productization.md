# 前端产品化重构实施计划

> 执行方式：inline（本会话直接执行；本环境约束不允许子代理）。验证方式：`npm run build` + 无头 Chrome 截图（非 TDD——视觉重构的验收是渲染结果）。

**Goal:** 按 `docs/specs/2026-09-19-frontend-productization-design.md` 把 web/ 前端从「报表堆砌」升级为「产品级仪表盘」，保留现有靛蓝配色与系统字体。

**Architecture:** 纯前端。globals.css 扩充 token → 新组件（Skeleton）→ Nav 改版 → 四页重排。数据层 `lib/data.js`、引擎、Supabase 均不动。

**Tech Stack:** Next.js 15, recharts, lucide-react（新增）, 纯 CSS 变量主题。

---

### Task 1: 依赖 + 设计 token 扩充

**Files:** Modify `web/package.json`（npm install lucide-react）, `web/app/globals.css`

- [ ] `cd web && npm install lucide-react`
- [ ] globals.css `:root` / `[data-theme="light"]` 增补 token：
  - `--hover: color-mix(in srgb, var(--panel-2) 70%, var(--accent) 6%)`
  - `--focus-ring: 0 0 0 3px color-mix(in srgb, var(--accent) 35%, transparent)`
  - `--shadow-card`（深色 `0 1px 2px rgba(0,0,0,.35)`，浅色沿用现 shadow）
  - `--skel-base` / `--skel-shine`（骨架屏双色，深浅主题各一套）
- [ ] 全局规则：
  - `.num, .card .value, td.num, th.num` 加 `font-variant-numeric: tabular-nums;`
  - `a, button, select { transition: all .18s ease; }`
  - `:focus-visible { outline: none; box-shadow: var(--focus-ring); border-radius: 8px; }`
  - `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; } }`
  - `.card` hover：`border-color: color-mix(in srgb, var(--accent) 30%, var(--border))`
- [ ] 验证：`cd web && npm run build` 通过

### Task 2: 骨架屏组件

**Files:** Create `web/components/Skeleton.jsx`

- [ ] 组件：`<Skeleton variant="card|table|chart" rows={n} />`，CSS shimmer（`@keyframes skel-slide`，linear-gradient 扫过），尊重 reduced-motion
- [ ] globals.css 加 `.skel` 系列样式
- [ ] 四页把 `<Loading />`（全屏转圈保留给路由级 `app/loading.jsx`）替换为页面内骨架：首页=卡片+图表骨架，表格页=表格骨架
- [ ] 验证：截图 loading 态（用节流/直接看组件渲染）

### Task 3: Nav 改版

**Files:** Modify `web/components/Nav.jsx`

- [ ] lucide 图标：仪表盘 `LayoutDashboard`、交易 `ArrowLeftRight`、信号 `Radio`、复盘 `ClipboardCheck`；主题 `Sun`/`Moon`；数据源 `Cloud`/`HardDrive`（带绿/灰状态点）
- [ ] 每项 `icon + label`，active 态：accent 色图标 + 底部 2px accent 指示条
- [ ] 主题按钮 aria-label、≥32px 命中区、保留 localStorage 持久化与 `?theme=` 参数
- [ ] 验证：截图 nav 深色/浅色

### Task 4: 首页重排为「今日驾驶舱」

**Files:** Modify `web/app/page.jsx`

- [ ] 顺序：告警横幅 → 账户概览（净值曲线加大到 220px + 5 数字卡）→ **今日焦点**（新）→ 策略排行（+实盘状态徽章列，复用 reviewStats.evaluateStrategies）→ 回测曲线 → 热力图
- [ ] 今日焦点面板（数据均来自 loadOverview/loadSignalsData 已有字段）：
  - 信号分布：今日 CALL x / PUT y / FLAT z（badge 行；首页改用 loadOverview().signals？→ 不需要，overview 无 signals，用 `loadSignalsData()` 或直接在 export/aggregate 加 signals_summary；**决定：首页额外调用 loadSignalsData()（有缓存），取其 signals 数组统计**）
  - 浮亏最多 5 笔持仓（symbol+strategy+unrealized_pnl）
  - 3 天内到期持仓列表（dte_left ≤ 3，带倒计时 badge）
- [ ] 验证：截图深色+浅色

### Task 5: 交易明细页统计条

**Files:** Modify `web/app/trades/page.jsx`

- [ ] 筛选区下方加统计条：笔数 / 胜率 / 合计盈亏 / 平均每笔（随筛选实时变化）
- [ ] 数字列确认 tabular-nums 生效
- [ ] 验证：截图 + 切换筛选数值变化

### Task 6: 信号页持仓按策略分组

**Files:** Modify `web/app/signals/page.jsx`

- [ ] Open Paper Positions 表改为按 strategy 分组：组头行（策略名 + 组内笔数 + 组内合计权利金），组内按 symbol 排序
- [ ] 验证：截图

### Task 7: 复盘页对齐 + 全量验证

**Files:** Modify `web/app/review/page.jsx`（仅 token 级微调：图表高度、面板标题统一）

- [ ] 曲线图高度 220px 统一、面板标题样式统一
- [ ] 全量验证矩阵：
  - `npm run build` exit 0
  - 无头 Chrome 截图：4 页 × 深/浅主题 = 8 张，逐张查看
  - 375px 宽度抽查首页+复盘页
- [ ] 服务器保持 Supabase 模式运行，四页 200

---

## Self-Review

- Spec 覆盖：token/图标/骨架屏 ✓(T1-T3) 驾驶舱 ✓(T4) 交易统计条 ✓(T5) 持仓分组 ✓(T6) 复盘微调 ✓(T7) 双主题+375px 验证 ✓(T7)
- 无占位符；组件名/字段名与现有代码一致（loadOverview/loadSignalsData/evaluateStrategies 均已存在）
- 类型一致：positions 含 `strategy`/`unrealized_pnl`/`dte_left`（引擎已写入）
