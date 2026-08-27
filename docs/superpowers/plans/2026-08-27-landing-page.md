# Stock Monitor 宣传落地页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个单文件静态宣传落地页 `docs/宣传手册/landing.html`（A+B 混合：真实截图 + CSS 手绘示意），面向价值投资者，移动端优先，零个人数据暴露。

**Architecture:** 单文件 `landing.html` 内联全部 CSS 与轻量 JS（IntersectionObserver 滚动入场），零外部依赖；嵌入 1 张 Playwright 实拍的五段分析详情截图（脱敏：仅公共分析内容）；其余产品界面用 CSS 手绘示意并遵循演示值规范。截图存 `screens/` 独立 PNG，相对路径引用。

**Tech Stack:** 原生 HTML5 + CSS3（CSS 变量 + flex/grid + media queries）+ 原生 JS（IntersectionObserver）；验证用 Playwright MCP + grep。

## Global Constraints

- **数据脱敏（硬约束）**：真实截图仅取五段分析详情（公共分析内容），元素级截图避开顶部栏邮箱/侧边栏身份；仪表盘/持仓/自选看板/聊天一律 CSS 手绘；手绘示例股票用知名蓝筹（贵州茅台/五粮液/宁德时代/腾讯/长江电力），数字一律演示值；页面任何位置不出现真实邮箱、用户名、真实持仓金额。
- **品牌视觉**：主色 `#4D6EFE`；信号灯三色 green `#52c41a` / yellow `#faad14` / red `#ff4d4f`；A 股惯例红涨绿跌；浅色 DeepSeek 风。
- **零外部依赖**：不使用外部字体/CDN/图片；系统字体栈 `system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`；html 离线（file://）可打开。
- **CTA**：所有注册按钮 `href="http://49.232.171.206"`（新窗口打开，`target="_blank"`）。
- **移动端优先**：断点 ~768px；375~430px 视口无横向滚动。
- **专业口径**：扣非、PE 锚定、安全边际、逆向清单等术语规范使用，无事实性错误。
- **免责声明**：页脚含「股市有风险，投资需谨慎，本平台输出仅供研究参考，不构成投资建议」。
- 所有 commit message 以 `Co-Authored-By: Claude <noreply@anthropic.com>` 结尾。

---

### Task 1: 采集真实截图（五段分析详情，脱敏）

**Files:**
- Create: `docs/宣传手册/screens/five-stage-analysis.png`
- Create: `docs/宣传手册/screens/.gitkeep`（目录占位，若 screens 为空时避免 git 丢目录）

**Interfaces:**
- Consumes: 生产环境 http://49.232.171.206（登录账号 `1140467720@qq.com` / `da@7712025`）；生产已有贵州茅台 600519 的 DSH 五段分析结果
- Produces: `screens/five-stage-analysis.png`（Task 3 用 `<img src="screens/five-stage-analysis.png">` 嵌入）

- [ ] **Step 1: 登录生产并导航到股票分析详情页**

用 Playwright MCP：

1. `browser_navigate` → `http://49.232.171.206`
2. 若未登录：导航 `http://49.232.171.206/login`，`browser_snapshot` 找邮箱/密码输入框，`browser_type` 填 `1140467720@qq.com` 与 `da@7712025`，点登录按钮，等待跳转仪表盘
3. 导航 `http://49.232.171.206/stock/600519`（贵州茅台分析详情）
4. `browser_snapshot` 确认五段分析内容已渲染（含「击球区/逆向清单/总结」等区块；若该页无五段，改试 `http://49.232.171.206/analysis` 搜索 600519 进入分析结果页）

- [ ] **Step 2: 元素级截图（只截分析内容区）**

`browser_snapshot` 找到包含五段分析内容的容器元素 ref（页面主体内容容器，**不含**顶部栏邮箱/侧边栏用户信息）。用 `browser_take_screenshot` 的 `target` 参数对内容容器截图：

```
target: <分析内容容器 ref>
filename: screens/five-stage-analysis.png
scale: device
```

若容器过大，可先 `browser_resize` 到 1280×2400 再截图，保证关键分析段落完整。

- [ ] **Step 3: 脱敏复核截图**

用 `Read` 打开 `D:\project\github\stock-monitor\docs\宣传手册\screens\five-stage-analysis.png`，人工确认：

- 无顶部栏邮箱 `1140467720@qq.com`
- 无侧边栏用户名/头像
- 无个人备注/自定义内容
- 仅展示股票公共分析信息（护城河/风险/逆向清单/结论）

若发现个人数据：回到 Step 1 重新截取更窄的内容容器，或截图后用裁切重拍。

- [ ] **Step 4: 提交**

```bash
git add "docs/宣传手册/screens/"
git commit -m "docs(宣传手册): 采集五段分析真实截图（脱敏：仅公共分析内容）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 落地页骨架 + 设计基座 + 页头 + 页脚

**Files:**
- Create: `docs/宣传手册/landing.html`（首次 Write 完整骨架：`<head>` + 全部 CSS + `<header>` + `<main>` 内单锚点 `<!-- @@SECTION@@ -->` + `<footer>` + `<script>` 内 `/* @@JS@@ */` 锚点）

**Interfaces:**
- Consumes: Task 1 的截图（后续引用，本任务不嵌入）
- Produces: `landing.html` 骨架 + CSS 系统（CSS 变量/组件类/响应式），后续任务 Edit 替换 `<!-- @@SECTION@@ -->` 追加区块、替换 `/* @@JS@@ */` 写动效

- [ ] **Step 1: Write 完整骨架**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock Monitor — 好价格下的好公司 · AI 价值投资分析平台</title>
<meta name="description" content="AI 驱动的 A 股安全边际分析平台：DSH 五段式分析、三色信号灯、持仓卖出分析、AI 投资小助手。好价格下的好公司，从一次分析开始。">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --brand:#4D6EFE;--brand-hover:#3D5EE0;--brand-soft:#E8EEFF;
  --green:#52c41a;--yellow:#faad14;--red:#ff4d4f;
  --ink:#1A1A1A;--ink-2:#555;--ink-3:#8A8A8A;
  --bg:#fff;--bg-soft:#F5F7FA;--border:#ECECEC;
  --radius:16px;
  --shadow:0 8px 30px rgba(77,110,254,.10);
  --shadow-lg:0 20px 50px rgba(77,110,254,.16);
}
html{scroll-behavior:smooth}
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink);background:var(--bg);line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px}
a{color:var(--brand);text-decoration:none}

/* 页头 */
.site-header{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.86);backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
.site-header .wrap{display:flex;align-items:center;justify-content:space-between;height:60px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;color:var(--ink)}
.brand .logo{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,var(--brand),#7B8EFF);display:grid;place-items:center;color:#fff;font-size:15px;font-weight:800}
.nav{display:flex;align-items:center;gap:22px;font-size:14px;color:var(--ink-2)}
.nav a:hover{color:var(--brand)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;border-radius:10px;font-weight:600;cursor:pointer;transition:.18s;border:none}
.btn-primary{background:var(--brand);color:#fff;padding:10px 22px;font-size:15px}
.btn-primary:hover{background:var(--brand-hover);transform:translateY(-1px)}
.btn-ghost{background:transparent;color:var(--ink-2);padding:9px 18px;font-size:14px;border:1px solid var(--border)}
.btn-ghost:hover{border-color:var(--brand);color:var(--brand)}
.btn-lg{padding:14px 34px;font-size:16px;border-radius:12px}

/* 区块通用 */
.section{padding:76px 0}
.section-soft{background:var(--bg-soft)}
.eyebrow{display:inline-flex;align-items:center;gap:6px;color:var(--brand);font-weight:600;font-size:13px;letter-spacing:.04em;background:var(--brand-soft);padding:5px 12px;border-radius:999px;margin-bottom:14px}
.section h2{font-size:30px;line-height:1.3;font-weight:700;margin-bottom:12px}
.lead{color:var(--ink-2);font-size:16px;max-width:640px}
.center{text-align:center}
.center .lead{margin:0 auto}

/* 滚动入场 */
.reveal{opacity:0;transform:translateY(22px);transition:opacity .6s ease,transform .6s ease}
.reveal.in{opacity:1;transform:none}

/* 卡片 */
.card{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:26px;box-shadow:var(--shadow)}

/* 页脚 */
.site-footer{border-top:1px solid var(--border);padding:34px 0 44px;color:var(--ink-3);font-size:13px;text-align:center;line-height:2}
.disclaimer{background:var(--bg-soft);border-radius:10px;padding:14px 18px;margin:0 auto 18px;max-width:820px;text-align:left;font-size:13px;color:var(--ink-3)}

/* 响应式 */
@media (max-width:768px){
  .section{padding:56px 0}
  .section h2{font-size:25px}
  .nav .nav-links{display:none}
  .btn-lg{padding:13px 26px;font-size:15px}
}
</style>
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <div class="brand"><span class="logo">投</span>Stock Monitor</div>
    <nav class="nav">
      <span class="nav-links"><a href="#features">核心功能</a><a href="#method">投资方法论</a><a href="#data">数据能力</a><a href="#start">快速上手</a></span>
      <a class="btn btn-primary" href="http://49.232.171.206" target="_blank" rel="noopener">立即使用</a>
    </nav>
  </div>
</header>
<main>
<!-- @@SECTION@@ -->
</main>
<footer class="site-footer">
  <div class="wrap">
    <div class="disclaimer">免责声明：本平台所有分析输出仅供投资研究参考，不构成任何投资建议。股市有风险，投资需谨慎。据此操作，风险自担。</div>
    <div>© 2026 Stock Monitor · AI 价值投资分析平台 · <a href="http://49.232.171.206" target="_blank" rel="noopener">访问产品</a></div>
  </div>
</footer>
<script>
/* @@JS@@ */
</script>
</body>
</html>
```

- [ ] **Step 2: 本地打开自检**

用 Playwright MCP 导航 `file:///D:/project/github/stock-monitor/docs/%E5%AE%A3%E4%BC%A0%E6%89%8B%E5%86%8C/landing.html`（URL 需百分号编码中文路径），`browser_console_messages` 确认 0 errors，`browser_take_screenshot` 确认页头/页脚渲染正常（正文为空属预期，Task 3 起填充）。

- [ ] **Step 3: 提交**

```bash
git add "docs/宣传手册/landing.html"
git commit -m "docs(宣传手册): 落地页骨架 + 设计基座（CSS 系统/页头/页脚）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Hero + 痛点共鸣区块

**Files:**
- Modify: `docs/宣传手册/landing.html`（Edit 替换 `<!-- @@SECTION@@ -->` 为两个区块 + 重新追加锚点）

**Interfaces:**
- Consumes: Task 2 的 CSS 类（`.hero` 等新类本任务补 CSS）
- Produces: Hero（含 CTA）+ 痛点区块；新增 `.hero`、`.pain-points`、`.pain-card`、`.hero-signals`、`.signal-pill` CSS

- [ ] **Step 1: 追加 Hero CSS + Hero HTML + 痛点 HTML**

在 `<style>` 中 `.section{...}` 之前 Edit 追加（用旧锚点替换为新内容 + 新锚点）：

CSS 追加（插到 `.site-footer` 规则之前）：

```css
/* Hero */
.hero{padding:96px 0 84px;text-align:center;position:relative;overflow:hidden;background:
  radial-gradient(900px 420px at 50% -80px,var(--brand-soft),transparent 70%)}
.hero h1{font-size:52px;line-height:1.18;font-weight:800;letter-spacing:-.01em;margin-bottom:18px}
.hero h1 .accent{color:var(--brand)}
.hero .sub{font-size:18px;color:var(--ink-2);max-width:620px;margin:0 auto 30px}
.hero-cta{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin-bottom:48px}
.hero-signals{display:flex;gap:16px;justify-content:center;flex-wrap:wrap;max-width:820px;margin:0 auto}
.signal-card{flex:1;min-width:210px;background:var(--bg);border:1px solid var(--border);border-radius:14px;padding:16px 18px;text-align:left;box-shadow:var(--shadow)}
.signal-card .sg-name{font-weight:700;font-size:15px;display:flex;align-items:center;gap:8px;margin-bottom:8px}
.signal-card .sg-desc{font-size:13px;color:var(--ink-2)}
.signal-card .sg-tag{font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px}
.sg-green{color:#1d7a08;background:rgba(82,196,26,.14)}
.sg-yellow{color:#ad6b00;background:rgba(250,173,20,.16)}
.sg-red{color:#c13c3e;background:rgba(255,77,79,.13)}

/* 痛点 */
.pain-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:40px}
.pain-card{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:24px}
.pain-card .p-emoji{font-size:26px;margin-bottom:10px}
.pain-card h3{font-size:16px;margin-bottom:8px}
.pain-card p{font-size:14px;color:var(--ink-2)}
.solve-box{margin-top:34px;background:var(--brand-soft);border-radius:var(--radius);padding:24px 26px;font-size:15px;color:var(--ink)}
.solve-box strong{color:var(--brand)}
@media (max-width:768px){
  .hero{padding:64px 0 56px}
  .hero h1{font-size:34px}
  .hero .sub{font-size:16px}
  .pain-grid{grid-template-columns:1fr}
}
</style>
```

（将上述 CSS 块 Edit 插入到 `</style>` 前，同时把正文锚点替换。）

HTML（Edit 替换 `<!-- @@SECTION@@ -->`）：

```html
<section class="hero">
  <div class="wrap">
    <span class="eyebrow reveal">AI 价值投资分析平台</span>
    <h1 class="reveal">好价格下的<br>好公司<span class="accent">。</span></h1>
    <p class="sub reveal">将成文的价值投资方法论工程化为 AI 分析流水线。<br>输入任意 A 股 / 港股代码，输出五段式分析报告与三色信号灯。</p>
    <div class="hero-cta reveal">
      <a class="btn btn-primary btn-lg" href="http://49.232.171.206" target="_blank" rel="noopener">立即免费使用 →</a>
      <a class="btn btn-ghost btn-lg" href="#features">了解核心功能</a>
    </div>
    <div class="hero-signals reveal">
      <div class="signal-card"><div class="sg-name"><span class="sg-tag sg-green">🟢 击球区</span></div><div class="sg-desc">当前价格已在安全边际区间，可配置/买入</div></div>
      <div class="signal-card"><div class="sg-name"><span class="sg-tag sg-yellow">🟡 观察区</span></div><div class="sg-desc">距离击球区 0~50%，等待更好时机</div></div>
      <div class="signal-card"><div class="sg-name"><span class="sg-tag sg-red">🔴 高估区</span></div><div class="sg-desc">当前价格远离安全边际，坚决放弃/太难</div></div>
    </div>
  </div>
</section>

<section class="section" id="pain">
  <div class="wrap">
    <div class="center">
      <span class="eyebrow reveal">投资中的三大困境</span>
      <h2 class="reveal">为什么大多数散户<br class="m-hide">赚不到钱？</h2>
      <p class="lead reveal">问题往往不在「不够努力」，而在「没有系统」。</p>
    </div>
    <div class="pain-grid">
      <div class="pain-card reveal"><div class="p-emoji">🎯</div><h3>凭感觉买卖</h3><p>追涨杀跌、听消息跟风，缺乏可重复的判断标准，涨了拿不住、跌了死扛。</p></div>
      <div class="pain-card reveal"><div class="p-emoji">📊</div><h3>看不懂财报</h3><p>商业模式、护城河、扣非净利润、行业合理估值——多数人缺乏系统方法去判断「一家公司到底值多少钱」。</p></div>
      <div class="pain-card reveal"><div class="p-emoji">⚖️</div><h3>没有纪律</h3><p>该买时犹豫、该卖时贪心，情绪主导决策，缺少一条铁律来约束自己。</p></div>
    </div>
    <div class="solve-box reveal"><strong>Stock Monitor 的解法：</strong>把一套成文的价值投资方法论（8 项原则 + 五段式分析 + 14 道逆向清单）工程化为可重复执行的 AI 流水线——让每一次判断都有方法、有依据、有纪律，帮您像机构投资者一样思考。</div>
  </div>
</section>
<!-- @@SECTION@@ -->
```

- [ ] **Step 2: 本地视口自检**

Playwright 导航 `file:///.../landing.html`，`browser_resize` 375×812 与 1440×900 各截一次图，确认：Hero 文案居中、信号灯三卡换行合理、CTA 按钮完整、无横向滚动（`browser_evaluate` 检查 `document.documentElement.scrollWidth <= innerWidth`）。

- [ ] **Step 3: 提交**

```bash
git add "docs/宣传手册/landing.html"
git commit -m "docs(宣传手册): Hero + 痛点共鸣区块

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 核心功能区块（五段分析 + 信号灯 + 持仓卖出 + AI 助手 + 笔记记忆）

**Files:**
- Modify: `docs/宣传手册/landing.html`（Edit 替换 `<!-- @@SECTION@@ -->`）

**Interfaces:**
- Consumes: Task 1 截图 `screens/five-stage-analysis.png`；Task 3 锚点
- Produces: `#features` 区块；新增 `.feature-grid`、`.feature-card`、`.shot-frame`、`.mock-ui`、`.mock-board`、`.mock-row`、`.mock-chat`、`.mock-diary` 等 CSS

- [ ] **Step 1: 追加功能区块 CSS + HTML**

CSS 追加（`</style>` 前）：

```css
/* 核心功能 */
.feature-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:44px}
.feature-card{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:28px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:14px}
.feature-card h3{font-size:18px;display:flex;align-items:center;gap:10px}
.feature-card .f-tag{font-size:12px;font-weight:600;color:var(--brand);background:var(--brand-soft);padding:2px 10px;border-radius:999px}
.feature-card p{font-size:14px;color:var(--ink-2)}
.feature-card.wide{grid-column:1/-1}
.steps-list{margin:8px 0 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:8px}
.steps-list li{font-size:13px;color:var(--ink);background:var(--bg-soft);border:1px solid var(--border);border-radius:999px;padding:5px 12px}
.steps-list li b{color:var(--brand)}
.shot-frame{border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--bg);box-shadow:var(--shadow);position:relative}
.shot-frame img{display:block;width:100%;height:auto}
.shot-frame .shot-caption{position:absolute;left:12px;bottom:12px;font-size:12px;color:#fff;background:rgba(26,26,26,.66);padding:3px 10px;border-radius:999px}
@media (max-width:768px){.feature-grid{grid-template-columns:1fr}.feature-card.wide{grid-column:auto}}
</style>
```

HTML（替换锚点）：

```html
<section class="section section-soft" id="features">
  <div class="wrap">
    <div class="center">
      <span class="eyebrow reveal">核心功能</span>
      <h2 class="reveal">从「看代码」到「看公司」</h2>
      <p class="lead reveal">五段式分析 + 实时信号灯 + 持仓纪律，一站式覆盖选股、持有、卖出全流程。</p>
    </div>
    <div class="feature-grid">

      <div class="feature-card wide reveal">
        <h3>🔬 DSH 五段式分析 <span class="f-tag">AI 核心引擎</span></h3>
        <p>DSH 分析引擎自动采集实时行情与近 8 期财报，注入只读上下文，按五段执行系统性分析——每一步都有方法，结论可溯源。</p>
        <ul class="steps-list">
          <li><b>① 定性</b>商业模式 / 护城河 / 经营质量</li>
          <li><b>② PE 锚定</b>行业合理估值区间</li>
          <li><b>③ 击球区</b>安全边际量化</li>
          <li><b>④ 逆向清单</b>14 道证伪提问</li>
          <li><b>⑤ 结论</b>先结论后建议</li>
        </ul>
        <div class="shot-frame reveal"><img src="screens/five-stage-analysis.png" alt="DSH 五段式分析结果页（示意截图）"><span class="shot-caption">五段式分析 · 真实产品界面</span></div>
      </div>

      <div class="feature-card reveal">
        <h3>🟢🟡🔴 三色信号灯</h3>
        <p>自选股实时安全边际监控看板：30 分钟行情刷新 + 16:00 收盘重算，信号一目了然。</p>
        <div class="mock-ui">
          <div class="mock-row"><span class="m-code">600519 贵州茅台</span><span class="m-tag g">🟢 击球区</span><span class="m-dist">距击球区 -8%</span></div>
          <div class="mock-row"><span class="m-code">000858 五粮液</span><span class="m-tag y">🟡 观察区</span><span class="m-dist">距击球区 +18%</span></div>
          <div class="mock-row"><span class="m-code">300750 宁德时代</span><span class="m-tag r">🔴 高估区</span><span class="m-dist">距击球区 +73%</span></div>
        </div>
      </div>

      <div class="feature-card reveal">
        <h3>💼 持仓卖出分析</h3>
        <p>持仓股走 position 模式：4 大卖出原则 + 2 大规避陷阱，给出距卖出区信号——该持有还是该卖出，AI 帮你把纪律想清楚。</p>
        <div class="mock-ui">
          <div class="mock-row"><span class="m-code">00700 腾讯控股</span><span class="m-tag g">🟢 持有</span><span class="m-dist">距卖出区 -25%</span></div>
          <div class="mock-row"><span class="m-code">000333 美的集团</span><span class="m-tag y">🟡 接近</span><span class="m-dist">距卖出区 -8%</span></div>
          <div class="mock-row"><span class="m-code">601318 中国平安</span><span class="m-tag r">🔴 建议卖出</span><span class="m-dist">距卖出区 +12%</span></div>
        </div>
      </div>

      <div class="feature-card reveal">
        <h3>🤖 AI 投资小助手</h3>
        <p>资深价值投资聊天机器人：SSE 流式对话、实时查询行情财报、L0→L3 记忆蒸馏——越聊越懂你的投资画像。</p>
        <div class="mock-ui mock-chat">
          <div class="m-bubble bot">贵州茅台当前快照：现价 ¥1,346，动态 PE ≈ 20.4，处于 🟡 观察区。商业模式与护城河已纳入五段分析，建议结合逆向清单评估安全边际。</div>
          <div class="m-bubble user">帮我分析下宁德时代值不值得买？</div>
        </div>
      </div>

      <div class="feature-card reveal">
        <h3>📒 投资笔记 + 记忆</h3>
        <p>Markdown 笔记 + 文件夹树，边写边存；@ 引用笔记即可让 AI 深度分析。你的每一次决策、复盘，都会蒸馏成越来越懂你的投资记忆。</p>
      </div>

    </div>
  </div>
</section>
<!-- @@SECTION@@ -->
```

本任务新增 CSS 需含手绘 UI 组件（一并插入）：

```css
/* 手绘 UI 示意（脱敏：演示数据） */
.mock-ui{background:var(--bg-soft);border:1px solid var(--border);border-radius:12px;padding:12px;display:flex;flex-direction:column;gap:8px}
.mock-row{display:flex;align-items:center;justify-content:space-between;gap:8px;background:var(--bg);border:1px solid var(--border);border-radius:9px;padding:8px 12px;font-size:13px}
.mock-row .m-code{font-weight:600;color:var(--ink)}
.mock-row .m-dist{color:var(--ink-3);font-variant-numeric:tabular-nums}
.m-tag{font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px}
.m-tag.g{color:#1d7a08;background:rgba(82,196,26,.14)}
.m-tag.y{color:#ad6b00;background:rgba(250,173,20,.16)}
.m-tag.r{color:#c13c3e;background:rgba(255,77,79,.13)}
.mock-chat{gap:10px}
.m-bubble{border-radius:10px;padding:9px 12px;font-size:13px;line-height:1.55;max-width:88%}
.m-bubble.bot{background:var(--bg);border:1px solid var(--border);align-self:flex-start;color:var(--ink)}
.m-bubble.user{background:var(--brand-soft);color:var(--ink);align-self:flex-end}
</style>
```

> 注：Task 4 共三次 CSS 追加均可合并为一次 Edit（在 `</style>` 前统一插入两段 CSS + 在 `<main>` 内替换锚点）。示例股票与数值均为演示值，**与真实生产数据无对应关系**。

- [ ] **Step 2: 截图嵌入 + 脱敏复核**

1. 确认 `screens/five-stage-analysis.png` 存在且引用路径正确（相对 `landing.html` 所在目录）
2. 用 Playwright 打开本地页，`browser_snapshot` 检查五段截图 `<img>` 已渲染（`browser_take_screenshot` 截图自查）
3. **脱敏 grep**（Bash，确认手绘区无真实个人数据）：
   `grep -nE "1140467720|da@|真实用户|QQ|持股|成本" docs/宣传手册/landing.html` → 期望 0 命中（若命中即改演示值）

- [ ] **Step 3: 提交**

```bash
git add "docs/宣传手册/landing.html"
git commit -m "docs(宣传手册): 核心功能区块（五段分析截图 + 手绘 UI 示意，脱敏）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 方法论背书 + 数据能力 + 快速上手 + CTA 收尾

**Files:**
- Modify: `docs/宣传手册/landing.html`（Edit 替换 `<!-- @@SECTION@@ -->`）

**Interfaces:**
- Consumes: Task 4 锚点
- Produces: `#method`、`#data`、`#start` 区块 + 底部 CTA；新增 `.principle-grid`、`.principle`、`.checklist`,`.data-chips`、`.steps`、`.cta-band` CSS

- [ ] **Step 1: 追加 CSS + HTML**

CSS 追加（`</style>` 前）：

```css
/* 方法论 */
.principle-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:40px}
.principle{background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:18px}
.principle .p-idx{font-size:12px;font-weight:700;color:var(--brand);background:var(--brand-soft);width:24px;height:24px;border-radius:8px;display:grid;place-items:center;margin-bottom:10px}
.principle h4{font-size:14px;margin-bottom:6px}
.principle p{font-size:12px;color:var(--ink-2)}
.checklist-note{margin-top:34px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:26px}
.checklist-note .cn-title{font-weight:700;font-size:16px;margin-bottom:10px}
.checklist-note ul{padding-left:20px;font-size:14px;color:var(--ink-2);display:grid;grid-template-columns:1fr 1fr;gap:8px 24px}
.checklist-note li::marker{color:var(--brand)}
/* 数据能力 */
.data-chips{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:34px}
.data-chip{background:var(--bg);border:1px solid var(--border);border-radius:999px;padding:12px 22px;font-size:14px;font-weight:600;color:var(--ink);box-shadow:var(--shadow)}
.data-chip b{color:var(--brand)}
/* 快速上手 */
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:40px}
.step{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:26px;position:relative}
.step .s-num{font-size:30px;font-weight:800;color:var(--brand-soft);-webkit-text-stroke:1px var(--brand);line-height:1}
.step h4{font-size:16px;margin:12px 0 8px}
.step p{font-size:14px;color:var(--ink-2)}
/* CTA */
.cta-band{margin-top:0;background:linear-gradient(135deg,var(--brand),#6C80FF);color:#fff;border-radius:22px;padding:56px 30px;text-align:center}
.cta-band h2{color:#fff}
.cta-band p{color:rgba(255,255,255,.85);margin-bottom:28px;font-size:16px}
.btn-white{background:#fff;color:var(--brand);padding:14px 36px;font-size:16px;border-radius:12px;font-weight:700}
.btn-white:hover{transform:translateY(-1px);box-shadow:0 12px 30px rgba(0,0,0,.18)}
@media (max-width:768px){
  .principle-grid{grid-template-columns:repeat(2,1fr)}
  .steps{grid-template-columns:1fr}
  .checklist-note ul{grid-template-columns:1fr}
}
</style>
```

HTML（替换锚点）：

```html
<section class="section" id="method">
  <div class="wrap">
    <div class="center">
      <span class="eyebrow reveal">投资方法论</span>
      <h2 class="reveal">一套可执行的<br class="m-hide">价值投资体系</h2>
      <p class="lead reveal">不是玄学，不是黑箱——8 项原则 + 14 道逆向清单，全部工程化写入分析引擎。</p>
    </div>
    <div class="principle-grid">
      <div class="principle reveal"><div class="p-idx">1</div><h4>利润质量优先</h4><p>扣非净利润口径，挤掉水分</p></div>
      <div class="principle reveal"><div class="p-idx">2</div><h4>保守年化</h4><p>H1×2 优先，不赌高增长</p></div>
      <div class="principle reveal"><div class="p-idx">3</div><h4>行业 PE 锚定</h4><p>估值回归行业合理区间</p></div>
      <div class="principle reveal"><div class="p-idx">4</div><h4>多元估值校验</h4><p>多视角交叉验证内在价值</p></div>
      <div class="principle reveal"><div class="p-idx">5</div><h4>证伪优先</h4><p>逆向清单先找推翻的理由</p></div>
      <div class="principle reveal"><div class="p-idx">6</div><h4>好公司 ≠ 好投资</h4><p>价格决定买不买</p></div>
      <div class="principle reveal"><div class="p-idx">7</div><h4>评级可修正</h4><p>新证据随时更新判断</p></div>
      <div class="principle reveal"><div class="p-idx">8</div><h4>输出结论</h4><p>结论在前，不输出冗长过程</p></div>
    </div>
    <div class="checklist-note reveal">
      <div class="cn-title">🕵️ 14 道逆向投资反问清单</div>
      <ul>
        <li>如果我是竞争对手，会如何击溃它？</li>
        <li>公司最大的三个风险是什么？</li>
        <li>核心优势 5 年内会被颠覆吗？</li>
        <li>财报里有哪些数字让我不舒服？</li>
        <li>增速减半，还值得买吗？</li>
        <li>估值永远回不到历史均值呢？</li>
        <li>最脆弱的假设错了会怎样？</li>
        <li>市场情绪是否已反映在价格中？</li>
        <li>为什么别人没看到这个机会？</li>
        <li>我是理性分析还是 FOMO？</li>
        <li>手握现金，还会按现价买吗？</li>
        <li>再跌 30%，我扛得住吗？</li>
        <li>所有问题能轻松回答吗？</li>
        <li>反面证据能推翻我的逻辑吗？</li>
      </ul>
    </div>
  </div>
</section>

<section class="section section-soft" id="data">
  <div class="wrap center">
    <span class="eyebrow reveal">数据能力</span>
    <h2 class="reveal">真实数据 · 多渠道保障</h2>
    <p class="lead reveal">腾讯 + 东方财富公开 HTTP 多渠道 provider 链，主备自动切换，行情永不阻断。</p>
    <div class="data-chips">
      <div class="data-chip reveal">📈 <b>A 股 + 港股</b> 全覆盖</div>
      <div class="data-chip reveal">🔄 <b>30 分钟</b> 行情刷新</div>
      <div class="data-chip reveal">⏰ <b>16:00</b> 收盘自动重算</div>
      <div class="data-chip reveal">📊 <b>近 8 期</b> 财报自动采集</div>
      <div class="data-chip reveal">🛡️ <b>多渠道</b> 主备自动切换</div>
    </div>
  </div>
</section>

<section class="section" id="start">
  <div class="wrap">
    <div class="center">
      <span class="eyebrow reveal">快速上手</span>
      <h2 class="reveal">三分钟，开始你的第一次分析</h2>
    </div>
    <div class="steps">
      <div class="step reveal"><div class="s-num">1</div><h4>注册账号</h4><p>邮箱即可注册，数据按用户隔离，隐私安全。</p></div>
      <div class="step reveal"><div class="s-num">2</div><h4>添加自选 / 持仓</h4><p>搜索股票即可添加，无需手填代码、行情、行业。</p></div>
      <div class="step reveal"><div class="s-num">3</div><h4>一键 AI 分析</h4><p>触发五段式分析，看信号灯，得结论，有纪律地执行。</p></div>
    </div>
  </div>
</section>

<section class="section" id="cta">
  <div class="wrap">
    <div class="cta-band reveal">
      <h2>好价格下的好公司<br>从一次分析开始</h2>
      <p>注册即用，无需信用卡。把每一次买卖，都变成有方法、有依据、有纪律的决策。</p>
      <a class="btn btn-white btn-lg" href="http://49.232.171.206" target="_blank" rel="noopener">立即免费使用 →</a>
    </div>
  </div>
</section>
<!-- @@SECTION@@ -->
```

- [ ] **Step 2: 本地视口自检**

Playwright 打开本地页，375×812 与 1440×900 截图自查：原则网格换行合理、清单两列/单列正确、步骤卡完整、CTA 渐变带文案不溢出、无横向滚动。

- [ ] **Step 3: 提交**

```bash
git add "docs/宣传手册/landing.html"
git commit -m "docs(宣传手册): 方法论 + 数据能力 + 快速上手 + CTA 区块

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 滚动动效 JS + 响应式收尾 + README + 全量验证

**Files:**
- Modify: `docs/宣传手册/landing.html`（Edit 替换 `/* @@JS@@ */`）
- Create: `docs/宣传手册/README.md`

**Interfaces:**
- Consumes: Task 5 完成后的完整页面
- Produces: 可发布交付物 + 部署说明

- [ ] **Step 1: 写滚动入场 JS（替换 `/* @@JS@@ */`）**

```html
(function(){
  var els = document.querySelectorAll('.reveal');
  if(!('IntersectionObserver' in window)){els.forEach(function(e){e.classList.add('in')});return}
  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(en){ if(en.isIntersecting){ en.target.classList.add('in'); io.unobserve(en.target) } })
  }, {threshold:.12});
  els.forEach(function(e){ io.observe(e) });
})();
```

- [ ] **Step 2: README**

创建 `docs/宣传手册/README.md`：

```markdown
# Stock Monitor 宣传落地页

单文件静态宣传页，零外部依赖，离线可打开。

## 本地预览

直接用浏览器打开 `landing.html` 即可（截图走相对路径 `screens/`）。

## 内容与脱敏

- 真实截图仅 1 张：`screens/five-stage-analysis.png`（DSH 五段分析详情，公共分析内容，已脱敏）
- 其余界面为 CSS 手绘示意，示例股票与数字均为演示值，不含任何真实用户数据
- 若需更新截图：登录生产，元素级截取五段分析内容区，替换同名 PNG 即可

## 部署到生产（可选）

将 `landing.html` 与 `screens/` 放入 nginx 静态目录，作为独立路径 `/about` 提供：

1. 服务器 `frontend_dist` 卷中新建 `about/` 目录，拷入两个文件
2. nginx location 添加：
   ```nginx
   location = /about { try_files /about/landing.html =404; }
   location /about/screens/ { alias /usr/share/nginx/html/about/screens/; }
   ```
3. `docker compose exec nginx nginx -s reload`

> 注意：落地页不替换产品 SPA 首页 `/`，避免影响现有用户入口。
```

- [ ] **Step 3: 全量验证清单**

1. **离线可开**：Playwright 打开 `file:///.../landing.html`，`browser_console_messages` 0 errors；`browser_evaluate` 确认 `document.readyState==='complete'`
2. **双视口无横向滚动**：375×812 与 1440×900 下 `document.documentElement.scrollWidth <= innerWidth` 均 true
3. **CTA 可达**：Bash `grep -oE 'href="http://49\.232\.171\.206"' docs/宣传手册/landing.html | wc -l` ≥ 3（页头 + Hero + CTA 收尾）
4. **脱敏全页复核**：`grep -nE "1140467720|da@|QQ 邮箱|持股|成本价|用户名" docs/宣传手册/landing.html docs/宣传手册/screens/` 期望 0 命中；人工 `Read` 截图与 html 再扫一遍
5. **滚动动效**：Playwright 滚动页面，`.reveal.in` 元素数量随滚动增长（首屏除外）

- [ ] **Step 4: 提交**

```bash
git add "docs/宣传手册/"
git commit -m "docs(宣传手册): 滚动动效 + README 部署说明 + 全量验证

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- 8 区块内容结构 → Task 3（Hero/痛点）、Task 4（核心功能）、Task 5（方法论/数据/上手/CTA）、Task 2（页脚免责声明）
- 视觉风格（#4D6EFE/信号灯三色/浅色）→ Task 2 CSS 变量
- 脱敏硬约束 → Task 1（截图仅公共内容）、Task 4/6（grep 复核）、手绘演示值规范
- CTA → 三个位置 `http://49.232.171.206`，验证 ≥3
- 移动端优先 → 各任务 viewport 自检
- README + `/about` 部署说明 → Task 6

**Placeholder scan:** 无 TBD/TODO；所有步骤含实际代码/命令；唯一锚点 `<!-- @@SECTION@@ -->` / `/* @@JS@@ */` 为明确的追加位置标记，非内容占位。

**Type consistency:** CSS 类名（`.reveal`/`.mock-*`/`.signal-card`/`.principle`/`.step`）在各任务定义与使用一致；截图路径 `screens/five-stage-analysis.png` 在 Task 1 产出、Task 4 引用一致；CTA URL 常量一致。

**注意（实施者）：** 生产登录凭据在 `docs/宣传手册/README.md` 中**不要**出现（脱敏）；Task 1 使用生产截图时不要提交任何含凭据的日志。
