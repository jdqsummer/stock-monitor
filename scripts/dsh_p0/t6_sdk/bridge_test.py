"""DSH Python SDK 连接探针：验证 deepseek-harness-sdk 真实用法与进程内外结论。

结论先行（详见 verify_report.md T6 小节）：
- SDK 是「进程内」模型：`HarnessClient.start()` 总是 `subprocess.Popen` 子进程，经
  stdin/stdout NDJSON JSON-RPC 通信；**无 TCP/HTTP/socket transport，无法连接
  「独立运行的 DSH 进程」（进程外）**。
- 真实构造参数 = `DeepSeekHarnessConfig`（dataclass）：provider / model / max_tokens /
  cwd / runtime_cwd / session_root / cordis / env / runtime_bin / launch_args_override /
  request_timeout_seconds / shutdown_timeout_seconds / base_url / api_key。
- `DeepSeekHarness.run(input, session_id=...)` 支持 session_id 复用（上下文延续）。

本脚本不依赖真 DSH runtime exe（仅 linux/macos），用本地 fake_runtime.py 作为
`runtime_bin` 拉起子进程，验证「进程内 spawn + stdio JSON-RPC + session_id 复用」。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DSH_P0 = HERE.parent
REPO_ROOT = DSH_P0.parent.parent
HARNESS = REPO_ROOT / "scripts" / "dsh_p0" / "deepseek-harness"

# 把 SDK 源码 + sdk-runtime 源码加到 sys.path（不污染 backend 依赖，不做 pip install）
sys.path.insert(0, str(HARNESS / "python" / "sdk" / "src"))
sys.path.insert(0, str(HARNESS / "python" / "sdk-runtime" / "src"))

from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig, RunResult  # noqa: E402


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    # ---- 1. 真实构造参数（verbatim，来自 DeepSeekHarnessConfig dataclass 字段） ----
    section("DeepSeekHarnessConfig 真实字段（构造参数）")
    import dataclasses
    for f in dataclasses.fields(DeepSeekHarnessConfig):
        print(f"  {f.name}: {f.type} = {f.default!r}")

    # ---- 2. 进程内模型：runtime_bin 指向本地 fake runtime，SDK 拉起子进程 ----
    section("进程内连接（runtime_bin = fake_runtime.py，SDK 自己 spawn 子进程）")
    fake = str(HERE / "fake_runtime.py")
    with DeepSeekHarness(
        provider="deepseek-official",
        model="deepseek-v4-flash",
        runtime_bin=sys.executable,
        launch_args_override=(sys.executable, fake),  # 覆写 argv：python fake_runtime.py
    ) as harness:
        r1: RunResult = harness.run("第一轮：安全边际是什么", session_id="p0-probe-1")
        print(f"  run#1 final_response = {r1.final_response!r}")
        print(f"  run#1 finish_reason  = {r1.finish_reason!r}")
        print(f"  run#1 session_id     = {r1.session_id!r}")

        # 同一 session_id 复用 → fake runtime 的 turn 计数应递增（上下文延续证据）
        r2: RunResult = harness.run("第二轮：延续上一会话", session_id="p0-probe-1")
        print(f"  run#2 final_response = {r2.final_response!r}")
        print(f"  run#2 session_id     = {r2.session_id!r}")
        assert "turn=2" in r2.final_response, "session_id 复用未延续（turn 计数应递增）"

        # 不同 session_id → 独立会话
        r3: RunResult = harness.run("全新会话", session_id="p0-probe-2")
        print(f"  run#3 final_response = {r3.final_response!r}")
        assert "turn=1" in r3.final_response

    print("  ✅ SDK 进程内 spawn + stdio JSON-RPC + session_id 复用均验证通过")

    # ---- 3. 进程外能力：默认 bundled runtime 在本机（win32）无法解析 ----
    section("进程外能力判定：默认 bundled runtime 解析")
    try:
        with DeepSeekHarness() as h:
            h.start()
    except Exception as exc:  # noqa: BLE001
        print(f"  默认 bundled runtime 启动失败（预期，Windows 无 exe）：")
        print(f"    {type(exc).__name__}: {exc}")
    else:
        print("  （意外）默认 runtime 启动成功")

    # ---- 4. 进程外结论（源码依据） ----
    section("进程内 vs 进程外：源码结论")
    print("  HarnessClient.start() 固定 subprocess.Popen(stdin/stdout/stderr=PIPE)，")
    print("  唯一 transport = stdio NDJSON JSON-RPC（dsh-sdk-protocol JsonRpcLineTransport）。")
    print("  runtime_bin / bridge_bin / launch_args_override 都只是「SDK 自己 spawn 的子进程」")
    print("  的 argv 变体；无任何 TCP/HTTP/socket 连接「已运行进程」的入口。")
    print("  => 结论：SDK 仅支持进程内，不支持连接独立 dsh-engine 进程（进程外）。")


if __name__ == "__main__":
    main()
