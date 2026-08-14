# AI 价值投资分析框架 · Harness 技术选型报告

> 版本：v1.0 ｜ 日期：2026-08-14 ｜ 模型：DeepSeek V4 ｜ 框架候选：OpenHarness vs DeepSeek Harness

---

## 一、项目背景与核心需求

构建一个 **AI 价值投资分析框架**，核心特征：

| 需求 | 说明 |
|------|------|
| **执行框架** | 采用 Harness 范式（Agent = Model + Harness），云端部署 |
| **体系沉淀** | 将用户的价值投资体系和经验 **Skill 化**，固化为可复用决策流程 |
| **核心能力** | 输入某支股票/企业，输出投资价值判断：价值判断标准、安全边际、投资策略 |
| **模型** | **DeepSeek V4**（V4-Pro / V4-Flash） |
| **辅助能力** | 投资笔记记录（经验输入模型）、会话保存（长期记忆）、多模型可切换 |

---

## 二、选型结论（TL;DR）

### ✅ 主选：DeepSeek Harness（DSH）

**核心决策依据：模型是 DeepSeek V4，DSH 是 DeepSeek 官方为其模型打造的运行时，第一方深度适配。** 当"模型供应商"与"框架供应商"一致时，适配成本、性能优化、版本演进同步性都是最优的。

**决策理由（按权重排序）：**

1. **V4 第一方适配（决定性）**：DSH 设置中默认预置 V4-Flash / V4-Pro 模型卡片，填入 API Key 即用；V4-Flash 正式版就是用 DSH 极简模式跑的官方基准测试；prefix-cache 实测命中率 99%（810 万 token 输入仅产生 4.64 万 token 输出）——价值投资分析需要大量财报/行情数据注入，成本优势直接放大。
2. **Skill 化能力完整（核心需求匹配）**：DSH 原生支持 Skill + **Agent Preset**——预设由配置文档构成，把系统提示词、工具、Skill、子 Agent、上下文压缩完整组合，正好支撑"投资体系经验化"+"多角色协作分析"。
3. **云端静默执行**：headless 模式 + `deepseek-harness-sdk`（Python）+ 三档沙箱（danger-full-access 可无人值守），适合云端后台服务。
4. **长期记忆生态**：社区已有"跨会话长期记忆 + 后台自我进化"插件（本地文件持久化 + 分层上下文注入 + LLM 自我整理），匹配投资笔记/经验沉淀需求。
5. **成本优势**：与 V4 深度优化的缓存机制 + 插件化免重复开发。

### ⚠️ 主要风险与对冲

| 风险 | 说明 | 对冲策略 |
|------|------|---------|
| **v0.1 开发者预览** | 2026-08-13 刚开源，核心插件和 API 将快速迭代，可能有破坏性变更 | 固定精确版本号；核心业务逻辑封装在自有抽象层，隔离 DSH 接口变化 |
| **不接收外部 PR** | DeepSeek 官方维护核心，社区只能贡献插件 | 所有定制通过插件形式做，不 fork 核心 |
| **生态待验证** | 插件生态刚起步 | OpenHarness 作为备用/对比基线，其 anthropics/skills 格式与 DSH 兼容，Skill 资产可复用 |

### 备选：OpenHarness（港大 HKUDS）

成熟稳定（v0.1.8、138 项测试全通过、11K 行代码复刻 Claude Code），通过 OpenAI 兼容层接入 DeepSeek。**适用场景**：若 DSH 在试跑阶段暴露严重稳定性问题，或团队更偏好 Python 纯血统实现，可平滑切换到 OpenHarness——Skill 资产（.md 格式）两边通用。

---

## 三、两框架详细对比

| 维度 | DeepSeek Harness (DSH) | OpenHarness (OH) | 胜者 |
|------|------------------------|------------------|:----:|
| **DeepSeek V4 适配** | 第一方预置 V4-Flash/Pro 卡片，默认 Base URL，prefix-cache 99% 命中 | OpenAI 兼容层接入（`deepseek-chat`），无特殊优化 | **DSH** |
| **Skill 体系** | 原生 Skill + Agent Preset（预设=工具+提示词+Skill+子Agent，可复制修改） | 兼容 anthropics/skills 格式（.md 按需加载，用户级/项目级路径） | **DSH** |
| **多角色 Agent** | Preset 内可编排子 Agent，作用域按 agent→preset→global 解析，同一进程多预设并行 | 子代理工具 + 计划模式，需自行编排 | **DSH** |
| **云端执行** | headless + Python SDK + ACP/JSON-RPC；三档沙箱可无人值守 | `oh -p` 非交互 + stream-json 事件流 + ohmo 网关（IM 通道） | **DSH**（集成更直接） |
| **长期记忆** | append-only 会话日志 + 社区记忆插件（跨会话+自我进化） | MEMORY.md + auto-dream 定期修剪 | **DSH** |
| **多模型切换** | 40+ 提供方卡片（Kimi/OpenAI/Anthropic/Google/自定义端点），模型路由即切即用 | 42 个 Provider Registry，5 类工作流 | 平手 |
| **沙箱安全** | Landlock (Rust) / Seatbelt / ACL 受限令牌，失败关闭原则 | 三级权限模式 + 路径规则 + SSRF 防护，无代码级沙箱 | **DSH** |
| **Web UI** | 原生 Web UI（:3080），UI 本身也是插件树 | TUI + CLI + Autopilot 看板 | **DSH** |
| **会话可恢复** | Resume / Fork / 回放，全部从事件日志重建 | 无对等能力 | **DSH** |
| **成熟度** | v0.1 开发者预览（刚发布 1 天），接口可能变更 | v0.1.8，138 项测试全通过，社区一年+积累 | **OH** |
| **语言** | TypeScript + Python + Rust（SDK 提供 Python） | Python 原生 | OH（Python 团队友好） |
| **许可** | MIT（不接收外部 PR） | MIT（活跃社区） | 平手 |
| **安装** | `npx @deepseek-ai/dsh` / `pip install deepseek-harness-sdk` | `pip install openharness-ai` | 平手 |

**评分汇总（满分 10）：**

| 维度 | 权重 | DSH | OH |
|------|:----:|:---:|:--:|
| V4 模型适配 | 30% | 10 | 7 |
| Skill 化能力 | 25% | 9 | 8 |
| 云端执行 | 20% | 9 | 8 |
| 长期记忆 | 15% | 9 | 7 |
| 成熟度稳定性 | 10% | 6 | 9 |
| **加权总分** | | **9.05** | **7.6** |

---

## 四、基于 DSH 的价值投资框架设计

### 4.1 五层架构（见架构图）

```
用户层       Web 前端 / API 网关（输入股票代码 → 输出价值报告）
  ↓
DSH 运行时   价值投资 Agent Preset（CIO 主 Agent + 财务/估值/风险 子 Agent）
  ↓
Skill 层     投资 Skill 体系（方法论/财务/估值/安全边际/笔记 · 按需加载）
  ↓
工具+记忆层  行情/财报/DCF 工具（权限+审计） ｜ append-only 会话日志 + 长期记忆插件
  ↓
模型层       DeepSeek V4（Pro 规划 · Flash 执行 · prefix-cache 降本）
```

### 4.2 Agent Preset 设计（核心资产）

DSH 的 Preset 是"一个会话的 Agent 运行的插件组装"（工具、提示词、能力）。为价值投资场景设计一个 **"价值投资分析官" 预设**：

```yaml
# value-investor.preset.yml（概念结构）
preset:
  id: value-investor
  system_prompt: |
    你是一位遵循严格价值投资方法论的首席投资官。
    决策必须基于事实数据与用户体系规则，禁止臆测。
    输出固定结构：企业画像 → 商业模式判断 → 财务质量 → 内在价值
    → 安全边际 → 投资策略建议。
  model:
    planner: deepseek-v4-pro      # 复杂规划与综合判断
    executor: deepseek-v4-flash   # 数据抓取、计算等高吞吐步骤
  skills:
    - methodology        # 用户价值投资体系
    - financial-analysis
    - valuation-models
    - margin-of-safety
    - notes-review
  subagents:
    - financial-analyst  # 三表解读、指标计算、造假信号
    - valuation-analyst  # DCF 多情景、相对估值、交叉验证
    - risk-officer       # 一票否决清单、风险标注
  tools:
    - market-quote       # 行情查询
    - financial-report   # 财报抓取
    - dcf-calculator     # DCF 计算器
    - web-search         # 行业/新闻检索
  memory:
    session-log: append-only    # 会话即真相，可回放
    long-term: memory-plugin    # 投资笔记 + 经验进化
  sandbox: workspace-write      # 生产可切换 danger-full-access
```

**多角色协作流**（以贵州茅台为例）：

```
用户输入 "分析贵州茅台（600519）"
  → CIO 调度：并行/顺序唤起 3 个子 Agent
  → 财务分析师：拉取近 5 年三表 → 计算 ROE/毛利率/自由现金流 → 造假信号扫描
  → 估值分析师：加载 DCF skill → 三情景折现（乐观/基准/悲观）→ 交叉相对估值
  → 风险官：跑一票否决清单（政策/管理层/财务异常）→ 标注剩余风险
  → CIO 综合：内在价值区间 → 安全边际 = (内在价值 - 现价)/内在价值
  → 输出：买入/观望/回避 结论 + 目标价区间 + 仓位建议
  → 自动写入投资笔记（决策依据留档）→ 长期记忆插件异步提炼经验
```

### 4.3 投资 Skill 体系（用户经验固化的载体）

每个 Skill 是符合 anthropics/skills 格式的 `.md` 操作手册（DSH 与 OH 通用，资产可移植）：

```
skills/
├── methodology/SKILL.md          # 价值投资核心原则、护城河、能力圈、商业模式
│   └── references/               # 用户体系细则、历史判例
├── financial-analysis/SKILL.md   # 三表解读、盈利/偿债/成长指标、造假识别
├── valuation-models/SKILL.md     # DCF 多情景、相对估值、资产基础法、交叉验证
├── margin-of-safety/SKILL.md     # 内在价值对比、安全边际计算、买卖阈值
└── notes-review/SKILL.md         # 决策笔记模板、复盘流程、错误归因、体系更新
```

**Skill 内容示例（margin-of-safety/SKILL.md 节选）：**

```markdown
# 安全边际判断手册

## 触发条件
当需要给出"买入/观望/回避"结论时自动加载。

## 决策规则（用户体系固化）
1. 内在价值 = DCF 基准情景估值 × 40% + 相对估值 × 40% + 资产基础 × 20%
2. 安全边际 = (内在价值 − 当前价格) / 内在价值
3. 阈值：
   - 安全边际 ≥ 30% → 买入区间（分批建仓）
   - 15% ≤ 安全边际 < 30% → 观望（等待更好价格）
   - 安全边际 < 15% → 回避（或仅持有不新增）
4. 一票否决：出现任一财务造假信号 / 治理重大瑕疵 → 直接回避

## 输出格式
必须给出：内在价值区间、当前价格、安全边际数值、结论标签、置信度。
```

**Skill 进化闭环**：复盘发现新规律 → 更新对应 Skill → 后续分析自动遵循 → 用户的"体系"随经验持续成长，这正是"经验输入模型"的落地形态。

### 4.4 云端部署方案（headless 静默执行）

```bash
# 方案 A：Python SDK（推荐，云端主路径）
pip install deepseek-harness-sdk
export DEEPSEEK_API_KEY="sk-xxx"
export DSH_MODEL="deepseek-v4-pro"
```

```python
from deepseek_harness import DeepSeekHarness

with DeepSeekHarness(
    provider="deepseek-official",
    model="deepseek-v4-pro",
    max_tokens=49_152,
    cwd="/workspace/investor",
    session_root="/data/sessions",
    cordis="presets/value-investor.cordis.yml",
) as harness:
    result = harness.run(
        "分析贵州茅台（600519），给出投资价值判断",
        session_id="maotai-2026-08-14",   # 复用 session_id 延续上下文
    )
    print(result.final_response)
```

**部署拓扑：**

| 组件 | 方案 |
|------|------|
| 前端 | Next.js / 自建 Web（或 DSH 原生 :3080 起步） |
| API 网关 | FastAPI，接 deepseek-harness-sdk，session_id 管理 |
| Agent 运行 | DSH headless + 自定义 Preset + danger-full-access 沙箱（全程审计） |
| 数据源 | 行情 API（腾讯自选股/东财）+ 财报抓取工具，注册为标准工具 |
| 记忆 | append-only 会话日志（/data/sessions）+ 长期记忆插件（投资笔记库） |
| 部署 | Docker（Node 22 + Python 3.10+）→ 生产 K8s |

---

## 五、实施路线图

| 阶段 | 周期 | 目标 | 验收标准 |
|------|------|------|---------|
| **P0 试跑验证** | 3-5 天 | 本地 `npx @deepseek-ai/dsh web` + V4 Key 跑通；用极简模式验证模型输出质量 | V4 接入成功，基础问答稳定 |
| **P1 Skill 沉淀** | 1-2 周 | 与用户逐条访谈投资体系 → 固化 5 个 Skill 包（含 references） | 每个 Skill 通过 3 个真实股票用例校验 |
| **P2 Preset 搭建** | 1 周 | 价值投资 Preset（CIO+3 子 Agent）+ 工具注册（行情/财报/DCF） | 完整跑通"输入股票→输出价值报告"链路 |
| **P3 云端化** | 1-2 周 | Python SDK 集成、API 网关、会话/记忆持久化、静默执行 | 云端 API 可用，session 可恢复 |
| **P4 生产加固** | 1-2 周 | 版本锁定、监控告警、沙箱策略、审计回放、成本优化（prefix-cache 调优） | 上线，压测稳定 |

**成本估算（参考）**：V4-Flash + prefix-cache（99% 命中）下，单次深度分析（约 50 万 token 输入）估算成本极低；建议 P0 阶段实测 20 次分析，统计 token 消耗后确定定价。

---

## 六、附录：关键事实来源

- DSH 于 **2026-08-13 正式开源**，v0.1 开发者预览，MIT 许可，Node 22+（SDK 提供 Python）
- V4-Flash 官方正式版评测即使用 DSH 极简模式；prefix-cache 命中率实测 99%
- DSH 原生支持：Skill、Agent Preset（四种预设：standard/minimal/code/cordis）、40+ 模型提供方、append-only 会话日志、Landlock 沙箱、Web UI、Resume/Fork
- OpenHarness：HKUDS 出品，11K 行复刻 Claude Code，138 项测试通过，通过 OpenAI 兼容层接入 DeepSeek
- 两框架 Skill 格式均兼容 anthropics/skills，**Skill 资产可双向迁移，选型可平滑切换**

---

*本报告为技术选型决策文档，具体实现细节将在 P0 试跑后根据 DSH 实际 API 迭代更新。*
