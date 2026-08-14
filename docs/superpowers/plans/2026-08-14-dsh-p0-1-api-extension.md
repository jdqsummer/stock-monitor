# DSH P0-1 扩展验证 Implementation Plan（深化项 API 验证）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 验证 spec `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 章节十三 4 项深化项（D1 PTC / D2 Session Fork / D6 Session Resume / Q3 Ralph）在 DSH v0.1 headless/SDK 路径下的真实可用性，回填章节十四组②决策表（决定对应深化项进 P2/P3/P4 还是走退路）；可选补充 prefix-cache API 层观测（T5），为 I7 成本模型提供实测数据。

**Architecture:** 探索性验证——延续 P0 T1-T7 模式，每个任务 = **源码侦察**（grep 定位真实 API 表面）→ **探针**（优先 CLI headless，其次 fake_runtime 协议级 / WSL2 真实 runtime）→ **结论记录**。验证结果追加 `scripts/dsh_p0/p0_1_verify_report.md`，T6 提炼为正式报告并回填 spec。

**Tech Stack:** Node 22+（本机便携 `node@22.23.2`）/ `@deepseek-ai/dsh@0.1.0-rc.6`（`scripts/dsh_p0` 已装）/ 源码 `scripts/dsh_p0/deepseek-harness` / `deepseek-harness-sdk`（Python）/ DEEPSEEK_API_KEY

## Global Constraints

- 版本锁定 `@deepseek-ai/dsh@0.1.0-rc.6`（精确，禁止 `^`/`~` 漂移），lockfile `pnpm-lock.yaml` + `frozen-lockfile`
- 运行时 Node ≥ 22.15.0（zstd 硬门槛，本机用便携 node@22.23.2）
- 本计划只做**验证**，不修改 `backend/` 生产代码、不删除任何现有文件（OpenHarness 退役在 P4）
- win32 无真实 SDK runtime exe：SDK 级探针用 `scripts/dsh_p0/t6_sdk/fake_runtime.py`（协议级，P0 已建成）或 WSL2/Docker（真实 runtime，spec「三、开发环境 I1」）
- CLI headless（`npx @deepseek-ai/dsh --profile headless "…"`）在 Windows 可跑（P0 T2 已验证）
- **源码侦察结论以执行时确认的源码为准**——本文档 P0 侦察引用的路径/关键词是线索，不是结论；每个任务必须先跑 grep 确认再下结论
- 所有记录写入 `scripts/dsh_p0/p0_1_verify_report.md`，commit 只提交验证文档与脚本，不提交 node_modules / DSH 安装产物

---

### Task 1: D1 PTC / Code Mode 可用性验证

**Files:**
- Create: `scripts/dsh_p0/p0_1_verify_report.md`（验证报告，本任务初始化）
- Create: `scripts/dsh_p0/p0_1_t1_ptc.mjs`（headless 工具清单探针）
- Modify: 无（只读源码）

**Interfaces:**
- Consumes: `scripts/dsh_p0` 的 DSH 安装（rc.6）、`DEEPSEEK_API_KEY`
- Produces: **D1 结论**（PTC 是否存在 / 若不存在走 invest-data-tool 批量封装退路）

- [ ] **Step 1: 初始化验证报告**

创建 `scripts/dsh_p0/p0_1_verify_report.md`：

```markdown
# DSH P0-1 扩展验证报告
> 目的：验证 spec 章节十三 D1/D2/D6/Q3 四项深化项 API 可用性，回填章节十四组②决策表。
> 日期：2026-08-14 · 分支：feat/dsh-p0-verification · DSH 版本：0.1.0-rc.6

## 验证清单
- [ ] T1 D1 PTC / Code Mode 可用性
- [ ] T2 D2 Session Fork 可用性
- [ ] T3 D6 Session Resume 语义
- [ ] T4 Q3 Ralph 循环触发
- [ ] T5 prefix-cache API 层观测（可选）
- [ ] T6 报告汇总与 spec 章节十四回填

## 详细记录
（每个 Task 追加：源码侦察命令与结论、探针命令与输出、结论、对 spec 章节十三对应项的决策）
```

- [ ] **Step 2: 源码侦察 PTC / Code Mode 落点**

Run（在 `scripts/dsh_p0/deepseek-harness` 下）：

```bash
cd scripts/dsh_p0/deepseek-harness
echo "=== ptc 关键词 ==="
grep -rli "ptc" packages/ --include="*.ts" | grep -v -i "test\|spec" | head -20
echo "=== code-runtime 包 ==="
ls packages/code-runtime/ 2>/dev/null && ls packages/code-runtime/*/src 2>/dev/null | head -20
echo "=== 模型可调用的 code/shell 工具（headless base preset 工具注册表）==="
cd ../ && npx @deepseek-ai/dsh --profile headless --dump-config 2>&1 | grep -iE "run_code|code|shell|execute|tool" | head -40
```

Expected: 判断 DSH v0.1 是否存在「PTC（Programmatic Tool Calling）」这一模式。P0 源码侦察提示 core/agent 无 `mode: ptc` 落点——**若 grep 无命中、dump-config 无 run_code 类工具，则 DSH v0.1 无 PTC**。

- [ ] **Step 3: 行为探针（确认模型侧是否只有单代码工具）**

若 Step 2 显示存在 `run_code`/`execute_code` 类工具，创建 `scripts/dsh_p0/p0_1_t1_ptc.mjs`：

```js
// D1 探针：验证模型是否被提供"单个代码工具批量调用数据接口"的能力（PTC/Code Mode）
export const task = [
  '你现在能看到的工具清单是什么？请逐个列出工具名。',
  '是否存在一个可以编写程序、在程序里批量调用其他数据工具的"代码执行"工具（类似 Code Interpreter / run_code）？',
  '如果有：请用它演示一次——写一段程序读取"行情 + 财报"两个数据接口并在程序内计算同比，只返回结论摘要。',
  '如果没有：请明确回答"DSH 当前没有代码执行工具"。',
].join('\n')
```

Run:

```bash
cd scripts/dsh_p0
node -e "import('./p0_1_t1_ptc.mjs').then(m => console.log(m.task))" > /tmp/t1_prompt.txt
npx @deepseek-ai/dsh --profile headless "$(cat /tmp/t1_prompt.txt)" 2>&1 | tail -40
```

Expected: 记录模型回答。若模型列出了 `run_code` 类工具且能批量调用 → D1 可用；若无 → D1 不成立。

- [ ] **Step 4: 记录结论并提交**

追加到 `p0_1_verify_report.md`：

```markdown
## T1 D1 PTC / Code Mode
- 源码侦察:（grep 命中/未命中，code-runtime 包存在性）
- 工具清单:（dump-config 列出的 code/shell 类工具）
- 行为探针:（模型是否可批量调工具只回结论）
- 结论: ✅ DSH v0.1 存在 PTC → spec D1 进 P2；❌ 不存在 → 走退路「invest-data-tool 内批量封装，单次调用返回聚合结果」
```

```bash
git add scripts/dsh_p0/p0_1_verify_report.md scripts/dsh_p0/p0_1_t1_ptc.mjs
git commit -m "chore(dsh-p0-1): T1 D1 PTC/Code Mode 可用性验证"
```

---

### Task 2: D2 Session Fork 可用性验证

**Files:**
- Create: `scripts/dsh_p0/p0_1_t2_fork.py`（SDK API 表面侦察 + fork 调用探针）
- Modify: `scripts/dsh_p0/p0_1_verify_report.md`

**Interfaces:**
- Consumes: `deepseek-harness-sdk`（Python）、`scripts/dsh_p0/t6_sdk/fake_runtime.py`（协议级 runtime）
- Produces: **D2 结论**（Fork API 是否存在 / 若不存在走 Orchestrator 串行重跑退路）

- [ ] **Step 1: 源码侦察 Fork API 表面**

Run（`scripts/dsh_p0/deepseek-harness` 下）：

```bash
cd scripts/dsh_p0/deepseek-harness
echo "=== session/sdk 中 fork 关键词 ==="
grep -rn -i "fork" packages/sdk/src packages/session/src packages/client/runtime/src 2>/dev/null | head -20
echo "=== SDK 暴露的会话方法（client/session）==="
grep -rn "public\|async \|method\s*=\|invoke\|call(" packages/client/runtime/src/client/sessions/session.ts 2>/dev/null | head -30
```

Expected: 判断 SDK/Session 层是否存在 `fork` 方法。P0 源码侦察提示：fork 仅出现在 `session-persistence/src/coordinator.ts` 的持久化注释（"persist a fork's seed once"），**SDK 客户端层大概率无 fork 原语**——以 grep 实际结果为准。

- [ ] **Step 2: SDK 运行时自省（权威确认）**

创建 `scripts/dsh_p0/p0_1_t2_fork.py`：

```python
"""D2 探针：确认 deepseek-harness-sdk 是否暴露 Session Fork API。

方法：
1. 定位 SDK 包源码目录（site-packages），grep fork/resume/restore 关键词。
2. 对 DeepSeekHarness / HarnessClient / Session 相关类做 dir() 自省，
   列出所有公开方法，检查是否存在 fork / forkSession / branch 类方法。
3. 若方法存在，尝试用 fake_runtime 拉起一次 fork 调用，观察线协议是否新增方法。
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path


def locate_sdk() -> Path:
    import deepseek_harness
    return Path(deepseek_harness.__file__).resolve().parent


def grep_sdk_src(root: Path, needles: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for p in root.rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        low = text.lower()
        for n in needles:
            if n in low:
                hits.append(f"{p.relative_to(root)}: {n}")
                break
    return hits


def introspect_methods(obj: object, prefix: str) -> list[str]:
    return [
        f"{prefix}.{name}"
        for name, _ in inspect.getmembers(obj, inspect.ismethod)
        if not name.startswith("_")
    ]


def main() -> None:
    root = locate_sdk()
    print(f"SDK 源码目录: {root}")
    print("--- grep fork / resume / restore / checkpoint ---")
    for h in grep_sdk_src(root, ("fork", "resume", "restore", "checkpoint")):
        print(" ", h)

    print("--- DeepSeekHarness 公开方法 ---")
    from deepseek_harness import DeepSeekHarness
    for m in introspect_methods(DeepSeekHarness, "DeepSeekHarness"):
        print(" ", m)

    # 若 Fork API 存在，这里会被调用（探针）；若不存在，python 直接 AttributeError = 结论证据
    # 尝试挂一个假 fork 调用，捕获结果
    print("--- fork 调用探针 ---")
    try:
        client = DeepSeekHarness.__new__(DeepSeekHarness)
        if hasattr(client, "fork"):
            print("发现 fork 方法！签名:", inspect.signature(client.fork))
        else:
            print("DeepSeekHarness 无 fork 方法")
    except Exception as exc:  # noqa: BLE001
        print(f"自省异常（记录即可）: {exc}")

    print("结论判定：若上述 grep 无命中且无 fork 方法 → DSH v0.1 SDK 无 Session Fork API")


if __name__ == "__main__":
    main()
```

Run:

```bash
cd scripts/dsh_p0
python p0_1_t2_fork.py 2>&1 | head -60
```

Expected: 输出 SDK 源码目录、fork/resume 关键词命中情况、DeepSeekHarness 公开方法列表。若 fork 相关方法缺失 → **D2 不成立，走退路「Orchestrator 串行触发两次额外分析（仅重跑 ④⑤ 步）」**。

- [ ] **Step 3: 记录结论并提交**

追加到 `p0_1_verify_report.md`：

```markdown
## T2 D2 Session Fork
- 源码侦察:（grep 命中/未命中；fork 仅持久化层注释 vs SDK 会话原语）
- SDK 自省:（公开方法列表；fork 方法存在性）
- 结论: ✅ SDK 暴露 Session Fork → spec D2 进 P3（Orchestrator 调 Fork API 做 ±10% 敏感性）；❌ 无 → 走退路「Orchestrator 串行两次重跑 ④⑤（仅重跑估值与结论）」
```

```bash
git add scripts/dsh_p0/p0_1_t2_fork.py scripts/dsh_p0/p0_1_verify_report.md
git commit -m "chore(dsh-p0-1): T2 D2 Session Fork 可用性验证"
```

---

### Task 3: D6 Session Resume 语义验证

**Files:**
- Create: `scripts/dsh_p0/p0_1_t3_resume.py`（SDK 复用会话探针：同 session_id 两轮 + checkpoint 语义）
- Modify: `scripts/dsh_p0/p0_1_verify_report.md`

**Interfaces:**
- Consumes: `deepseek-harness-sdk`、`scripts/dsh_p0/t6_sdk/fake_runtime.py`（P0 已证 session_id 复用 = 上下文延续）
- Produces: **D6 结论**（resume 语义 = 上下文延续 vs 显式断点恢复；重跑范围归谁）

- [ ] **Step 1: 源码侦察 checkpoint / resume 语义**

Run（`scripts/dsh_p0/deepseek-harness` 下）：

```bash
cd scripts/dsh_p0/deepseek-harness
echo "=== session-checkpoint-policy 作用 ==="
sed -n '1,80p' packages/session/session-checkpoint-policy/src/index.ts
echo "=== 是否暴露 restore/resume 原语给 SDK ==="
grep -rn -i "restore\|resume\|rehydrate" packages/session/session-checkpoint-policy/src 2>/dev/null | head -20
```

Expected: 判断 checkpoint 是「崩溃恢复（进程级）」还是「会话级显式断点恢复」。P0 源码侦察提示：checkpoint-policy 注入 `llm/sessionPersistence/sessions/tools`，作用是崩溃恢复 + 持久化——**大概率不是「从 ④ 步重跑」的会话原语**。

- [ ] **Step 2: SDK 行为探针（同 session 两轮注入新数据）**

创建 `scripts/dsh_p0/p0_1_t3_resume.py`：

```python
"""D6 探针：验证 session_id 复用语义 + 是否有显式 resume/restore 原语。

用 P0 的 fake_runtime 作为 runtime_bin 拉起 SDK（win32 无真实 exe），
同一 session_id 连续两轮 prompt，注入不同数据，观察：
1. 第二轮是否延续第一轮上下文（fake_runtime 的 seen 计数会体现）。
2. SDK 是否暴露 resume/restore 方法（自省，同 T2 模式）。
3. 结论推导：'从某步重跑' 是 Orchestrator 步骤级幂等职责，还是会话原语。
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "t6_sdk"))

from deepseek_harness import DeepSeekHarness

FAKE_RUNTIME = str(Path(__file__).resolve().parents[1] / "t6_sdk" / "fake_runtime.py")


def main() -> None:
    # 1) SDK 方法自省：找 resume / restore / rehydrate
    from deepseek_harness import DeepSeekHarness as H
    methods = [n for n, _ in inspect.getmembers(H, inspect.ismethod) if not n.startswith("_")]
    resume_like = [m for m in methods if any(k in m.lower() for k in ("resume", "restore", "rehydrate", "fork"))]
    print("SDK 方法: ", methods)
    print("resume/restore 类方法: ", resume_like)

    # 2) 同 session 两轮，验证上下文延续（fake_runtime 会回显 seen=turn）
    with DeepSeekHarness(
        provider="deepseek-official",
        model="deepseek-v4-flash",
        cwd=str(Path(__file__).resolve().parent),
        session_root=str(Path(__file__).resolve().parent / ".sessions"),
        runtime_bin=FAKE_RUNTIME,
    ) as harness:
        r1 = harness.run("第一轮：报告当前现价 1700 与 PE 28.5", session_id="p0-1-resume-600519")
        print("R1:", r1.final_response)
        r2 = harness.run("第二轮：现价已更新为 1750，请基于此重估结论", session_id="p0-1-resume-600519")
        print("R2:", r2.final_response)

    print("结论判定：")
    print("  - resume_like 非空 + 第二轮回显 turn=2 → 存在显式 resume 原语（记录签名）")
    print("  - resume_like 为空 + 第二轮回显 turn=2 → resume = 上下文延续，无断点恢复原语；'从某步重跑' 归 Orchestrator 步骤级幂等")
    print("  - 第二轮 turn=1（上下文不延续）→ session_id 复用不成立，需排查")


if __name__ == "__main__":
    main()
```

Run:

```bash
cd scripts/dsh_p0
python p0_1_t3_resume.py 2>&1 | tail -40
```

Expected: 第二轮回显 `turn=2`（上下文延续，与 P0 T6 一致）；resume 类方法大概率为空 → **D6 部分成立**：`session_id = code-date` 复用保证上下文延续（成本优势保留），但「从 ④ 步重跑」不是会话原语，须 Orchestrator 按数据新鲜度决定重跑步骤（spec 5.1 幂等 + 数据流已设计的 resume 流程需按此修正措辞）。

- [ ] **Step 3: 记录结论并提交**

追加到 `p0_1_verify_report.md`：

```markdown
## T3 D6 Session Resume
- checkpoint 语义:（崩溃恢复 vs 会话断点恢复）
- SDK resume 原语:（方法列表；存在性）
- 行为探针:（同 session 两轮 turn 计数；上下文延续性）
- 结论: ✅ 上下文延续成立（session_id 复用，P0 T6 复核）→ spec D6 的「续跑成本优势」成立；⚠️ 无显式断点恢复原语 → 「从 ④ 步重跑」改为 Orchestrator 步骤级幂等 + 数据新鲜度驱动（重跑 ②③④⑤ 或 ④⑤），回填 spec 5.1/章节十三 D6 措辞
```

```bash
git add scripts/dsh_p0/p0_1_t3_resume.py scripts/dsh_p0/p0_1_verify_report.md
git commit -m "chore(dsh-p0-1): T3 D6 Session Resume 语义验证"
```

---

### Task 4: Q3 Ralph 循环触发验证

**Files:**
- Create: `scripts/dsh_p0/p0_1_t4_ralph/prompt.mjs`（headless 探针 prompt）
- Create: `scripts/dsh_p0/p0_1_t4_ralph/ralph.patch.yml`（若 headless base 未注册 ralph-loop，则挂载）
- Modify: `scripts/dsh_p0/p0_1_verify_report.md`

**Interfaces:**
- Consumes: `tool-ralph`（DSH 内置 workflow 工具插件，`packages/workflow/tool-ralph`）、P0 T5 的插件挂载方式
- Produces: **Q3 结论**（headless 能否触发 Ralph 循环；触发方式）

- [ ] **Step 1: 读 tool-ralph 源码确认触发契约**

Run（`scripts/dsh_p0/deepseek-harness` 下）：

```bash
cd scripts/dsh_p0/deepseek-harness
echo "=== ralph-loop 工具名与参数 ==="
grep -n "name: '\|objective\|maxRounds\|description:" packages/workflow/tool-ralph/src/index.ts | head -20
echo "=== headless base preset 是否含 tool-ralph ==="
cd ../
npx @deepseek-ai/dsh --profile headless --dump-config 2>&1 | grep -iE "ralph|workflow" | head -20
```

Expected: 确认工具名（P0 源码侦察为 `ralph-loop`）、参数（`objective` + `maxRounds`）、是否已在 headless base preset 注册。

- [ ] **Step 2: 若未注册则挂载 ralph 工具**

若 Step 1 的 dump-config 无 `ralph-loop`，创建 `scripts/dsh_p0/p0_1_t4_ralph/ralph.patch.yml`（参考 P0 T4/T5 的 patch 与 composition 区别——裸插件行须走 composition/preset 目录，不能直接 `--patch`）：

```yaml
# 挂载 DSH 内置 tool-ralph（若 headless base 未注册）。
# 注意 P0 T4 坑位：composition（裸插件行）≠ patch（insert: 覆盖层）；
# 经 preset 目录 agent.cordis.yml 或 DSH_CORDIS_CONFIG 组合注入，勿用 --patch 裸文件。
ralph:
  # 每轮子 Agent 目标上限（默认 256，深度模式建议 1-3 轮）
  maxRounds: 3
```

并记录实际挂载方式（`dsh plugin add` / preset 目录 `agent.cordis.yml` / `DSH_CORDIS_CONFIG` 之一，以 P0 T4 实测可行为准）。

- [ ] **Step 3: CLI headless 触发探针**

创建 `scripts/dsh_p0/p0_1_t4_ralph/prompt.mjs`：

```js
// Q3 探针：headless 触发 Ralph 循环自审。
// 语义验证点：① ralph-loop 可被调用；② 每轮起新子 Agent（无上一轮推理上下文）；③ 结构化交接。
export const task = [
  '你是投资分析终审。请调用 ralph-loop 工具执行一次自审循环：',
  'objective="检查下列五段分析结论与信号灯评级是否一致，若发现矛盾给出修正建议。输入：最终评级 🟡、距击球区 32%（0-50% 应🟡），定性结论正向。返回 {verdict, issues[], suggestedRating}"',
  'maxRounds=2',
  '最后用一句话报告 Ralph 循环是否完成、roundsStarted 与 verdict。',
].join('\n')
```

Run：

```bash
cd scripts/dsh_p0
node -e "import('./p0_1_t4_ralph/prompt.mjs').then(m => console.log(m.task))" > /tmp/t4_prompt.txt
npx @deepseek-ai/dsh --profile headless "$(cat /tmp/t4_prompt.txt)" 2>&1 | tail -60
```

Expected: 模型调用 `ralph-loop`，返回 `{roundsStarted, report}` 结构 → **Q3 通过**（headless 可触发，进 P4 深度模式）；若工具不可见/报错 → 走退路「移除自审选项」。

- [ ] **Step 4: 记录结论并提交**

追加到 `p0_1_verify_report.md`：

```markdown
## T4 Q3 Ralph 循环
- 工具注册:（ralph-loop 是否在 headless base；挂载方式）
- 触发契约:（参数 objective/maxRounds；返回结构）
- 行为探针:（roundsStarted/verdict；每轮新子 Agent 语义是否体现）
- 结论: ✅ headless 可触发 → spec Q3 进 P4（深度模式，V4-Pro 开启）；❌ 不可触发 → 走退路「移除自审选项」
```

```bash
git add scripts/dsh_p0/p0_1_t4_ralph scripts/dsh_p0/p0_1_verify_report.md
git commit -m "chore(dsh-p0-1): T4 Q3 Ralph 循环触发验证"
```

---

### Task 5: prefix-cache API 层观测（可选，I7 成本模型输入）

**Files:**
- Create: `scripts/dsh_p0/p0_1_t5_prefix.py`（两次相同请求对比 usage）
- Modify: `scripts/dsh_p0/p0_1_verify_report.md`

**Interfaces:**
- Consumes: `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`（`scripts/dsh_p0/.env`）
- Produces: prefix-cache 命中率实测数据（回填 I7「99% 命中」假设；P0 报告第七节坑位 6 的后续）

- [ ] **Step 1: 写 API 层观测探针**

创建 `scripts/dsh_p0/p0_1_t5_prefix.py`（用标准库 urllib，免额外依赖；DeepSeek API 为 OpenAI 兼容 `/chat/completions`）：

```python
"""T5 探针：DeepSeek API 层观测 prompt cache 命中。

两次发送「完全相同」的请求（含相同 system 前缀），对比第二次 usage 中的
prompt_cache_hit_tokens / prompt_cache_miss_tokens，实测 prefix-cache 命中率。
用途：验证 spec 章节十三 I7「99% 命中」假设是否成立，为 D4 telemetry 的
生产监控指标（命中率）提供基准。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

# 读取 scripts/dsh_p0/.env 的 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL（不打印密钥）
env: dict[str, str] = {}
for line in (Path(__file__).resolve().parents[1] / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip("'\"")
    elif line.startswith("export "):
        k, _, v = line[7:].partition("=")
        env[k.strip()] = v.strip().strip("'\"")

API_KEY = env.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
BASE = (env.get("DEEPSEEK_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
MODEL = env.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

SYSTEM = "你是价值投资分析助手。八项原则：利润质量优先（扣非）、保守年化（H1×2 优先）、行业PE锚定、多元估值校验、证伪优先、好公司≠好投资、评级可修正、输出结论不输出过程。"
USER = "请分析贵州茅台（600519）当前是否处于安全边际击球区，用三句话回答。"


def call() -> dict:
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        "max_tokens": 200,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    if not API_KEY:
        print("DEEPSEEK_API_KEY 缺失，跳过")
        return
    for i in (1, 2):
        t0 = time.monotonic()
        data = call()
        usage = data.get("usage", {})
        hit = usage.get("prompt_cache_hit_tokens", 0)
        miss = usage.get("prompt_cache_miss_tokens", 0)
        total = usage.get("prompt_tokens", hit + miss)
        ratio = (hit / total * 100) if total else 0.0
        print(f"第 {i} 次: hit={hit} miss={miss} total={total} hit_rate={ratio:.1f}% 耗时={time.monotonic()-t0:.2f}s")
        time.sleep(3)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行并记录**

```bash
cd scripts/dsh_p0
python p0_1_t5_prefix.py 2>&1 | tail -10
```

Expected: 第二次请求 `hit_rate` 趋近 100% → 「99% 命中」假设成立（针对固定 persona/系统前缀）；若 API 不返回 cache 字段 → 记录「DeepSeek API 该模型/端点不可观测 cache」，I7 监控改走框架 token 计数（D4 telemetry）。

- [ ] **Step 3: 记录结论并提交**

追加到 `p0_1_verify_report.md`：

```markdown
## T5 prefix-cache API 层观测
- 实测:（第1/2次 hit_rate；是否返回 cache 字段）
- 结论: ✅「99% 命中」假设成立（固定前缀）→ I7 生产监控直接以 prompt_cache_hit_tokens 为指标；⚠️ 不可观测 → I7 改用 D4 telemetry 的 token 计数
```

```bash
git add scripts/dsh_p0/p0_1_t5_prefix.py scripts/dsh_p0/p0_1_verify_report.md
git commit -m "chore(dsh-p0-1): T5 prefix-cache API 层观测"
```

---

### Task 6: 报告汇总与 spec 章节十四回填

**Files:**
- Create: `docs/superpowers/plans/2026-08-14-dsh-p0-1-report.md`（正式报告，从 `p0_1_verify_report.md` 提炼）
- Modify: `docs/superpowers/specs/2026-08-14-dsh-integration-design.md`（章节十四组②表回填 + 若验证推翻 P0 侦察则修订正文）

**Interfaces:**
- Consumes: Task 1-5 全部记录
- Produces: **章节十四组②四项决策回填** + spec 相关章节措辞修正

- [ ] **Step 1: 提炼正式报告**

创建 `docs/superpowers/plans/2026-08-14-dsh-p0-1-report.md`：

```markdown
# DSH P0-1 扩展验证报告（正式）

> 日期：2026-08-14 · 分支：`feat/dsh-p0-verification` · DSH 版本：`0.1.0-rc.6`
> 来源：`scripts/dsh_p0/p0_1_verify_report.md`（T1-T5 追加记录）
> 目的：验证 spec 章节十三 D1/D2/D6/Q3 四项深化项 API 可用性，回填章节十四组②决策表。

## 一、深化项验证结论
| 深化项 | 验证结论 | 决策 | 退路/依据 |
|:--|:--|:--|:--|
| D1 PTC / Code Mode | （T1 结论） | 通过 → P2 / 失败 → invest-data-tool 批量封装 | 章节十三 D1 |
| D2 Session Fork | （T2 结论） | 通过 → P3 / 失败 → Orchestrator 串行重跑 ④⑤ | 章节十三 D2 |
| D6 Session Resume | （T3 结论） | 部分成立 → P3（重跑范围改 Orchestrator 幂等） | 章节十三 D6 |
| Q3 Ralph | （T4 结论） | 通过 → P4 深度模式 / 失败 → 移除自审 | 章节十三 Q3 |

## 二、prefix-cache 实测（T5，可选）
（hit_rate 实测值；对 I7 成本模型的影响）

## 三、对 spec 的修订清单
（列出因验证结果需要修订的 spec 章节：如 D6 措辞、D1 载体、章节十四组②表状态）
```

- [ ] **Step 2: 回填 spec 章节十四组②决策表**

用 Edit 更新 `docs/superpowers/specs/2026-08-14-dsh-integration-design.md` 章节十四「组② P0 验证后决策」表中 D1/D2/D6/Q3 四行的「P0 验证结果」与「结论」列：

```markdown
| D1 PTC | （P0-1 T1 实测结果） | （通过 → P2 实施 / 失败 → invest-data-tool 批量封装退路） |
| D2 Session Fork | （P0-1 T2 实测结果） | （通过 → P3 实施 / 失败 → Orchestrator 串行两次重跑退路） |
| D6 Session Resume | （P0-1 T3 实测结果） | （部分成立 → P3，重跑范围改 Orchestrator 步骤级幂等） |
| Q3 Ralph 自审 | （P0-1 T4 实测结果） | （通过 → P4 深度模式 / 失败 → 移除自审选项） |
```

同步更新章节十二修订追踪表新增的「D1-D4 深化项待验证」行状态列 →「已验证（P0-1 T1-T4）」。

- [ ] **Step 3: 修订受影响正文**

按验证结果修订 spec 受影响小节（仅当验证推翻 P0 侦察假设才改正文，其余只改组②表）：
- D6 若部分成立：修订章节十三 D6「落地载体」——从「DSH SDK 的 Resume API 调用」改为「Orchestrator 步骤级幂等 + session_id 复用上下文延续，重跑范围由数据新鲜度驱动」。
- D1 若失败：修订章节十三 D1「落地载体」——从「workflow ① 步声明 mode: ptc」改为「invest-data-tool 内批量封装，单次调用返回聚合摘要」。
- 其余项同理，以实测结论为准，并同步更新章节十二修订追踪表状态列。

- [ ] **Step 4: 自检验证报告**

对照 spec 章节十三「P0 验证清单更新」四项（PTC 可用性 / Fork API / Resume API / Ralph 触发方式）——检查 `2026-08-14-dsh-p0-1-report.md` 是否逐项回答了可用性，并给出通过/失败/退路决策。不足则补测。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-08-14-dsh-p0-1-report.md docs/superpowers/specs/2026-08-14-dsh-integration-design.md
git commit -m "docs(dsh-p0-1): 扩展验证报告汇总与 spec 章节十四组②回填"
```

- [ ] **Step 6: 续写 P1 plan**

P0-1 完成后，基于 `2026-08-14-dsh-p0-report.md` + `2026-08-14-dsh-p0-1-report.md` 的真实 API 签名，编写 `docs/superpowers/plans/2026-08-14-dsh-p1-assets-migration.md`（P1 资产迁移：SKILL 迁移含 E1/E2 + workflow 五段插件脚本 + 确定性 TS + 黄金数据集 + 组③ 全部项 + 附录 A），P2/P3/P4 依次类推。每个后续 plan 独立文档、独立交付。
