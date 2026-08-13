# Harness PoC 真实 DeepSeek 验证报告

## 概览

- 脚本：`scripts/harness_poc.py`（手动运行，不进测试）
- 引擎：开源 OpenHarness（`vendor/openharness/`）`QueryEngine` + `OpenAICompatibleClient`
- 适配层：`backend/agents/harness_component.py`（`create_harness_engine` / `collect_final_text` / `parse_output_json`）
- 运行时间：2026-08-13（本地，UTC+8）

## 模型与连接

- 模型：`deepseek-chat`
- API 格式：OpenAI 兼容（`base_url=https://api.deepseek.com/v1`）
- 客户端：`OpenAICompatibleClient`（`vendor/openharness/api/openai_client.py`），实现 `SupportsStreamingMessages` 协议
- 鉴权：`DEEPSEEK_API_KEY` 环境变量（未写入任何文件，未提交）

## 门禁 A：真实调用 + 事件流 + 解析

运行：

```bash
DEEPSEEK_API_KEY=xxx python scripts/harness_poc.py 600519
```

结果：

- 事件数：**159**（> 0）✓
- 最终文本：含 ```json 围栏 JSON 块 ✓
- `parse_output_json` 解析：成功提取 `final_rating` 与 `rationale` ✓

样例输出（首次运行）：

```json
{"final_rating": "🟡", "rationale": "护城河极强但估值略高，需等待更佳介入点位"}
```

**门禁 A：通过。**

## 门禁 B：输出稳定性（同一股票 600519 跑 5 次）

| 次数 | final_rating |
|:--|:--|
| 1 | 🟢 |
| 2 | 🟡 |
| 3 | 🟡 |
| 4 | 🟡 |
| 5 | 🟡 |

（另有门禁 A 的首次运行评级为 🟡；合计 6 次：5×🟡、1×🟢）

### 漂移说明（可解释）

5 次中 4 次 🟡、1 次 🟢，属相邻信号带（🟢/🟡 边界）的轻微漂移，**可解释**：

1. PoC 仅以自由文本「分析股票 600519」作为输入，未注入任何定量财务/安全边际数据，模型只能依据训练先验作答，评级停留在边界处（安全边际 0-50% 的 🟢/🟡 分界）。
2. 🟡 运行的 rationale 明确给出「估值略高、需等待更佳介入点位」，即处于边界价附近，正是 brief 所述的「边界价格」情形。
3. Phase 2 会将确定性的安全边际定量结果注入 state，锚定评级，此边界漂移将消失。

**门禁 B：通过（漂移可解释）。**

## 结论

PoC 门禁 A（真实 DeepSeek 调用 + 事件流 + 输出解析）与门禁 B（5 次稳定性、漂移可解释）均通过，可进入 Phase 2 全面迁移。
