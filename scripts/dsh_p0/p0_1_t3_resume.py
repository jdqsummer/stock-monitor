"""D6 探针：验证 session_id 复用语义 + 是否有显式 resume/restore 原语。

用 P0 的 fake_runtime 作为 runtime_bin 拉起 SDK（win32 无真实 exe），
同一 session_id 连续两轮 prompt，注入不同数据，观察：
1. 第二轮是否延续第一轮上下文（fake_runtime 的 turn 计数会体现）。
2. SDK 是否暴露 resume/restore/rehydrate 方法（自省 + hasattr，同 T2 模式）。
3. 结论推导：'从某步重跑' 是 Orchestrator 步骤级幂等职责，还是会话原语。

说明：本探针只做「SDK 表面自省 + fake_runtime 两轮复用」，不调用真实 DeepSeek API。
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "deepseek-harness"

# SDK 未 pip-install，直接挂源码 clone（load-bearing 注入，同 T2 / bridge_test.py）
sys.path.insert(0, str(HARNESS / "python" / "sdk" / "src"))
sys.path.insert(0, str(HARNESS / "python" / "sdk-runtime" / "src"))

from deepseek_harness import DeepSeekHarness, HarnessClient, Session  # noqa: E402

SDK_SRC = HARNESS / "python" / "sdk" / "src"
RUNTIME_SRC = HARNESS / "python" / "sdk-runtime" / "src"
FAKE_RUNTIME = str(HERE / "t6_sdk" / "fake_runtime.py")


def grep_src_roots(roots: list[Path], needles: tuple[str, ...]) -> list[str]:
    """python/sdk + python/sdk-runtime 源码内 resume/restore/rehydrate/fork 关键词命中。"""
    hits: list[str] = []
    for root in roots:
        if not root.exists():
            hits.append(f"[{root} 不存在]")
            continue
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


def public_methods(cls: type) -> list[str]:
    """类自身定义的公开方法名（排除 _ 前缀）。"""
    return [
        name
        for name, member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    ]


def resume_probe(obj: object, label: str) -> None:
    for name in ("resume", "restore", "rehydrate", "resume_session", "fork"):
        if hasattr(obj, name):
            attr = getattr(obj, name)
            try:
                sig = inspect.signature(attr)
            except (TypeError, ValueError):
                sig = "<无法取签名>"
            print(f"  命中: {label}.{name} 签名={sig}")
            return
    print(f"  未命中: {label} 无 resume/restore/rehydrate/resume_session/fork 方法")


def main() -> None:
    # 1) SDK 方法自省：找 resume / restore / rehydrate / fork
    print("=== SDK 源码 grep（resume/restore/rehydrate/fork）===")
    hits = grep_src_roots(
        [SDK_SRC, RUNTIME_SRC],
        ("resume", "restore", "rehydrate", "fork"),
    )
    if not hits:
        print("  （无命中）")
    for h in hits:
        print("  ", h)

    print("\n=== 公开方法自省 ===")
    for cls, label in ((DeepSeekHarness, "DeepSeekHarness"),
                       (Session, "Session"),
                       (HarnessClient, "HarnessClient")):
        methods = public_methods(cls)
        resume_like = [m for m in methods
                       if any(k in m.lower() for k in ("resume", "restore", "rehydrate", "fork"))]
        print(f"  {label} 方法: {methods}")
        print(f"  {label} resume/restore 类方法: {resume_like}")

    print("\n=== hasattr 探针 ===")
    resume_probe(DeepSeekHarness.__new__(DeepSeekHarness), "DeepSeekHarness(实例)")
    resume_probe(Session.__new__(Session), "Session(实例)")
    resume_probe(HarnessClient.__new__(HarnessClient), "HarnessClient(实例)")

    # 2) 同 session 两轮，验证上下文延续（fake_runtime 回显 turn 计数）
    print("\n=== 同 session 两轮（fake_runtime 作为 runtime_bin）===")
    with DeepSeekHarness(
        provider="deepseek-official",
        model="deepseek-v4-flash",
        cwd=str(HERE),
        session_root=str(HERE / ".sessions"),
        runtime_bin=sys.executable,
        launch_args_override=(sys.executable, FAKE_RUNTIME),  # 覆写 argv：python fake_runtime.py
    ) as harness:
        r1 = harness.run("第一轮：报告当前现价 1700 与 PE 28.5", session_id="p0-1-resume-600519")
        print("R1:", r1.final_response)
        r2 = harness.run("第二轮：现价已更新为 1750，请基于此重估结论", session_id="p0-1-resume-600519")
        print("R2:", r2.final_response)

    print("\n结论判定：")
    print("  - resume_like 非空 + 第二轮回显 turn=2 → 存在显式 resume 原语（记录签名）")
    print("  - resume_like 为空 + 第二轮回显 turn=2 → resume = 上下文延续，无断点恢复原语；'从某步重跑' 归 Orchestrator 步骤级幂等")
    print("  - 第二轮 turn=1（上下文不延续）→ session_id 复用不成立，需排查")


if __name__ == "__main__":
    main()
