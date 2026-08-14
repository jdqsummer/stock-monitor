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
for line in (Path(__file__).resolve().parents[0] / ".env").read_text(encoding="utf-8").splitlines():
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
