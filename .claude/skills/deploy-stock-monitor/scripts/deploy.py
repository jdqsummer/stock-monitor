#!/usr/bin/env python
"""一键部署 stock-monitor → 腾讯云服务器（49.232.171.206）。

流程：本地 pytest → 打包 tarball（排除 .env/.git/*.db/缓存）→ SFTP 上传 →
      备份服务器 .env → 解压覆盖代码 → 补 .env 缺失键 → docker compose up -d --build →
      轮询等 app 健康 → 全量验证（容器/health/前端/迁移/新表/多渠道数据源冒烟）。

用法:
  python deploy.py                # 全流程
  python deploy.py --skip-tests   # 跳过本地 pytest
  python deploy.py --dry-run      # 只打包 + 打印计划，不上传不部署
"""
import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time

from remote import Remote, RemoteError

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARBALL_NAME = "stock-monitor-deploy.tar.gz"

# docker buildkit/compose 的致命错误标记（出现即视为构建失败，避免空等超时）
BUILD_FAIL_MARKERS = (
    "error response from daemon",
    "failed to solve",
    "failed to build",
    "failed to compute",
    "error: failed",
    "executor failed running",
)


def load_config():
    with open(os.path.join(SCRIPT_DIR, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def step(msg):
    print(f"\n==> {msg}", flush=True)


def is_excluded(rel_path, excludes):
    """命中任意排除项（目录名或 fnmatch 模式如 *.db / .env）即排除。"""
    rel = rel_path.replace("\\", "/")
    parts = rel.split("/")
    for ex in excludes:
        if any(p == ex for p in parts):
            return True
        if fnmatch.fnmatch(rel, ex) or fnmatch.fnmatch(parts[-1], ex):
            return True
    return False


def pack(repo_dir, excludes, out_path):
    """把本地仓库打成 tarball；排除运行时/敏感/缓存文件。"""
    step(f"打包本地仓库 {repo_dir} -> {out_path}")
    if not os.path.isdir(repo_dir):
        raise SystemExit(f"本地仓库不存在: {repo_dir}，请检查 config.json 的 local_repo_dir")
    with tarfile.open(out_path, "w:gz") as tar:
        for root, dirs, files in os.walk(repo_dir):
            # 剪枝排除目录，避免遍历 node_modules 等大目录
            dirs[:] = [
                d for d in dirs
                if not is_excluded(os.path.relpath(os.path.join(root, d), repo_dir), excludes)
            ]
            for fname in files:
                fp = os.path.join(root, fname)
                rel = os.path.relpath(fp, repo_dir).replace("\\", "/")
                if is_excluded(rel, excludes):
                    continue
                tar.add(fp, arcname=rel)
    size = os.path.getsize(out_path)
    print(f"  打包完成: {size} bytes")
    return size


def run_local_tests(repo_dir):
    step("运行本地 pytest（部署前健康门禁，206 tests 需全过）")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    tail = (r.stdout or "")[-2000:].strip()
    if tail:
        print("  " + tail.replace("\n", "\n  "))
    if r.returncode != 0:
        raise SystemExit("  本地测试失败，中止部署。确认修复后重试，或用 --skip-tests 强制跳过。")
    print("  本地测试通过")


def apply_env_extra(remote, repo_dir, env_extra):
    """仅追加 .env 缺失的键，绝不覆盖服务器已有配置（含密钥）。"""
    if not env_extra:
        return
    step("补齐服务器 .env 配置（只追加缺失键）")
    for k, v in env_extra.items():
        cmd = (
            f"cd {repo_dir} && "
            f"if ! grep -q '^{k}=' .env; then "
            f"printf '{k}={v}\\n' >> .env && echo '  added {k}'; "
            f"else echo '  {k} 已存在，跳过'; fi"
        )
        rc, out, err = remote.exec(cmd, timeout=30)
        print(out.strip())


def start_build(remote, repo_dir, log_path):
    step("后台启动 docker compose up -d --build（nohup，日志见 deploy.log）")
    # 用 exec_detach 不读 stdout，根治坑位 7 的 PipeTimeout；setsid 让后台进程脱离会话，channel 关闭不影响
    rc, out, err = remote.exec_detach(
        f"cd {repo_dir} && setsid nohup docker compose up -d --build > {log_path} 2>&1 < /dev/null & disown"
    )
    print(out.strip())


def wait_for_app_healthy(remote, repo_dir, log_path, timeout_sec=1200):
    """轮询 app 容器直到 healthy；构建失败则提前返回。

    以 deploy.log（本次构建输出）为准：先查 buildkit 致命标记（命中即失败），
    再查 compose 是否已输出 "app-1 Healthy"。不直接信任 `docker compose ps` 的
    healthy——旧容器 healthy + build 失败时（Recreate 未发生）ps 会误报成功。
    """
    step(f"等待 app 容器健康（轮询，最长 {timeout_sec // 60} 分钟）")
    start = time.time()
    while time.time() - start < timeout_sec:
        time.sleep(10)
        # 1) 构建失败提前退出（compose/buildkit 日志含致命标记）
        rc, tail, _ = remote.exec(f"tail -80 {log_path} 2>/dev/null", timeout=30)
        low = (tail or "").lower()
        if any(m in low for m in BUILD_FAIL_MARKERS):
            print("  构建失败，日志摘录：")
            print((tail or "")[-1500:])
            return False
        # 2) deploy.log 出现本次构建的 Healthy 标记才算成功（避免旧容器误报）
        if "app-1 healthy" in low or "stock-monitor-app-1 healthy" in low:
            rc, out, err = remote.exec(f"cd {repo_dir} && docker compose ps", timeout=30)
            if "healthy" in out.lower():
                print("  app 已 healthy")
                return True
    print("  等待超时。最后日志：")
    rc, tail, _ = remote.exec(f"tail -60 {log_path} 2>/dev/null", timeout=30)
    print((tail or "")[-2500:])
    return False


def resolve_app_container(remote, repo_dir):
    """动态解析 app 容器名/ID，避免 compose 项目名变化导致 docker exec 失败。"""
    rc, out, _ = remote.exec(f"cd {repo_dir} && docker compose ps -q app 2>/dev/null", timeout=30)
    cid = out.strip().splitlines()[0] if out.strip() else "stock-monitor-app-1"
    return cid


def verify(remote, repo_dir, app):
    """全量验证部署结果，全部通过返回 True。"""
    step("验证部署")
    checks = []

    def run(name, cmd, timeout=90):
        rc, out, err = remote.exec(cmd, timeout=timeout)
        text = (out or err).strip()
        ok = rc == 0 and "fail" not in text.lower()[:20]
        checks.append((name, ok, text))
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}")
        if text:
            print("      " + text[:400].replace("\n", "\n      "))

    run("容器状态", f"cd {repo_dir} && docker compose ps")
    run("health API", "curl -s -o /dev/null -w 'HTTP %{http_code}' http://127.0.0.1/api/health")
    run("前端页面", "curl -s -o /dev/null -w 'HTTP %{http_code}' http://127.0.0.1/")
    run("alembic 迁移到 head",
        f"docker exec {app} alembic current 2>&1 | tail -1")
    run("表与关键列",
        f"docker exec {app} python -c \"import sqlite3;c=sqlite3.connect('/app/data/stock_monitor.db');"
        "tables=[r[0] for r in c.execute(\\\"select name from sqlite_master where type='table' and name in "
        "('stock_snapshots','financials','analysis_snapshots')\\\")];"
        "need=['checklist_results','checklist_veto','checklist_summary'];"
        "cols=[r[1] for r in c.execute('PRAGMA table_info(analysis_snapshots)')];"
        "print('tables',tables);print('checklist',[x for x in need if x in cols]);"
        "assert set(need)<=set(cols),'FAIL: analysis_snapshots 缺列 %s' % (set(need)-set(cols))\"")
    return all(ok for _, ok, _ in checks)


def datasource_smoke(remote, app):
    """多渠道数据源冒烟：容器内直测腾讯行情 + 东财财报，验证生产数据链路。"""
    step("多渠道数据源冒烟测试（腾讯/东财/mock 链）")
    code = (
        "import asyncio\n"
        "from backend.data.westock_client import WestockClient\n"
        "async def main():\n"
        "    c = WestockClient()\n"
        "    print('PROVIDERS:', [type(p).__name__ for p in c.providers])\n"
        "    q = await c.fetch_quote('600519')\n"
        "    print('QUOTE_OK:', q.code, q.name, q.current_price, q.pe_dynamic)\n"
        "    s = await c.search_stock('茅台')\n"
        "    print('SEARCH_OK:', len(s), [x.code for x in s][:3])\n"
        "    fs = await c.fetch_financials('600519')\n"
        "    print('FIN_OK:', len(fs), 'periods; first:', fs[0].report_period, fs[0].revenue, fs[0].net_profit_parent)\n"
        "    await c.close()\n"
        "asyncio.run(main())\n"
    )
    rc, out, err = remote.exec_stdin(
        f"docker exec -i {app} python -", code, timeout=120)
    print(out.strip())
    if rc != 0:
        print("  STDERR:", err.strip()[:800])
        return False
    return "QUOTE_OK" in out and "FIN_OK" in out


def main():
    ap = argparse.ArgumentParser(description="一键部署 stock-monitor 到腾讯云")
    ap.add_argument("--skip-tests", action="store_true", help="跳过本地 pytest")
    ap.add_argument("--dry-run", action="store_true", help="只打包+打印计划，不上传不部署")
    args = ap.parse_args()

    cfg = load_config()
    repo_dir = cfg["local_repo_dir"]
    remote_dir = cfg["server_repo_dir"]
    tar_path = os.path.join(tempfile.gettempdir(), TARBALL_NAME)
    log_path = f"{remote_dir}/deploy.log"

    if not args.skip_tests:
        run_local_tests(repo_dir)
    else:
        print("[skip] 跳过本地 pytest")

    pack(repo_dir, cfg["tar_excludes"], tar_path)

    if args.dry_run:
        print("\n[DRY-RUN] 完成本地打包。下一步会："
              "SFTP 上传 → 备份服务器 .env → 解压覆盖代码 → 补 env 缺失键 → "
              "docker compose up -d --build → 轮询 app 健康 → 全量验证。")
        return

    r = Remote(cfg)
    try:
        r.connect()
        # 1. 上传
        step("SFTP 上传部署包")
        r.upload(tar_path, f"/home/ubuntu/{TARBALL_NAME}")
        print(f"  已上传 {TARBALL_NAME}")

        # 2. 备份服务器 .env（含密钥，改动前必备份）
        step("备份服务器 .env")
        rc, out, err = r.exec(
            f"cp {remote_dir}/.env /home/ubuntu/.env.backup-$(date +%Y%m%d) && echo 'backed up'",
            timeout=30)
        print(out.strip())

        # 3. 解压覆盖（.env / deploy.log 不在包内，天然保留）
        step("解压覆盖代码")
        rc, out, err = r.exec(
            f"tar -xzf /home/ubuntu/{TARBALL_NAME} -C {remote_dir}/ && echo extracted", timeout=60)
        print(out.strip())
        rc, out, _ = r.exec(f"ls -d {remote_dir}/.env && echo '.env 保留'", timeout=30)
        print("  " + out.strip())

        # 4. 补 .env 缺失键
        apply_env_extra(r, remote_dir, cfg["env_extra"])

        # 5. 重建容器
        start_build(r, remote_dir, log_path)
        if not wait_for_app_healthy(r, remote_dir, log_path):
            raise SystemExit("  部署失败：app 未健康。查看 deploy.log 定位。")

        # 6. 验证
        app = resolve_app_container(r, remote_dir)
        ok = verify(r, remote_dir, app)
        smoke_ok = datasource_smoke(r, app)
        ok = ok and smoke_ok
        print(f"\n{'='*50}\n部署{'成功 ✅' if ok else '部分失败 ⚠️（见上方 FAIL 项）'}"
              f"（数据源冒烟测试 {'通过' if smoke_ok else '失败'}）")
        sys.exit(0 if ok else 1)
    finally:
        r.close()
        if os.path.exists(tar_path):
            os.remove(tar_path)


if __name__ == "__main__":
    main()
