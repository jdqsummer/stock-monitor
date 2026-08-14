"""D2 探针：确认 deepseek-harness-sdk（Python SDK）是否暴露 Session Fork API。

方法：
1. 注入 SDK 源码路径（SDK 未 pip-install，直接挂源码 clone），定位 deepseek_harness 包目录。
2. grep fork/resume/restore/checkpoint/branch 关键词（python/sdk + python/sdk-runtime 源码）。
3. 对 DeepSeekHarness / Session / HarnessClient 做 dir()/inspect 自省，列出公开方法，
   检查是否存在 fork / fork_session / branch / resume 类方法。
4. hasattr 探针：三类对象逐一探测 fork 相关方法存在性（存在则打印签名，不存在即结论证据）。

说明：本探针只做 API 表面侦察，不拉起 runtime、不调用 DeepSeek API（headless 不属于 T2）。
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "deepseek-harness"

# SDK 未 pip-install，直接挂源码 clone（与 t6_sdk/bridge_test.py 同一注入方式）
sys.path.insert(0, str(HARNESS / "python" / "sdk" / "src"))
sys.path.insert(0, str(HARNESS / "python" / "sdk-runtime" / "src"))

from deepseek_harness import (  # noqa: E402
    DeepSeekHarness,
    DeepSeekHarnessConfig,
    HarnessClient,
    Session,
)

SDK_SRC = HARNESS / "python" / "sdk" / "src"
RUNTIME_SRC = HARNESS / "python" / "sdk-runtime" / "src"


def locate_sdk() -> Path:
    import deepseek_harness
    return Path(deepseek_harness.__file__).resolve().parent


def grep_src_roots(roots: list[Path], needles: tuple[str, ...]) -> list[str]:
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
    """类自身定义的公开方法名（排除 _ 前缀与继承自 object 的项）。"""
    return [
        name
        for name, member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    ]


def fork_probe(obj: object, label: str) -> None:
    for name in ("fork", "fork_session", "forkSession", "branch"):
        if hasattr(obj, name):
            attr = getattr(obj, name)
            try:
                sig = inspect.signature(attr)
            except (TypeError, ValueError):
                sig = "<无法取签名>"
            print(f"  命中: {label}.{name} 签名={sig}")
            return
    print(f"  未命中: {label} 无 fork/fork_session/forkSession/branch 方法")


def main() -> None:
    sdk_pkg = locate_sdk()
    print(f"SDK 包目录: {sdk_pkg}")
    print(f"SDK 源码根: {SDK_SRC}")
    print(f"SDK-runtime 源码根: {RUNTIME_SRC}")

    print("\n--- grep fork / resume / restore / checkpoint / branch ---")
    hits = grep_src_roots(
        [SDK_SRC, RUNTIME_SRC],
        ("fork", "resume", "restore", "checkpoint", "branch"),
    )
    if not hits:
        print("  （无命中）")
    for h in hits:
        print("  ", h)

    print("\n--- DeepSeekHarness 公开方法 ---")
    for m in public_methods(DeepSeekHarness):
        print("  ", f"DeepSeekHarness.{m}")

    print("\n--- Session 公开方法 ---")
    for m in public_methods(Session):
        print("  ", f"Session.{m}")

    print("\n--- HarnessClient 公开方法 ---")
    for m in public_methods(HarnessClient):
        print("  ", f"HarnessClient.{m}")

    print("\n--- fork 调用探针（hasattr）---")
    # 用 __new__ 绕过 __init__（__init__ 会构建 HarnessClient，无需真实 runtime）
    fork_probe(DeepSeekHarness.__new__(DeepSeekHarness), "DeepSeekHarness(实例)")
    fork_probe(Session.__new__(Session), "Session(实例)")
    fork_probe(HarnessClient.__new__(HarnessClient), "HarnessClient(实例)")

    print("\n结论判定：")
    print("  若上述 grep 无命中（python/sdk 源码无 fork 关键词）且三类对象无 fork 方法")
    print("  → DSH Python SDK（deepseek-harness-sdk v0.1）无 Session Fork API → D2 走退路")


if __name__ == "__main__":
    main()
