#!/usr/bin/env python
"""paramiko 远程助手：连接腾讯云服务器执行命令 / SFTP 上传。

CLI 用法:
  python remote.py '<command>' [timeout]      # 远程执行命令
  python remote.py upload <local> [remote_name]  # 上传到 /home/ubuntu/

模块用法（供 deploy.py import）:
  from remote import Remote
  r = Remote()            # 读取同目录 config.json
  r.connect()
  rc, out, err = r.exec("docker compose ps", timeout=60)
  rc, out, err = r.exec_stdin("docker exec -i app python -", code, timeout=120)
  r.upload(local_path, remote_path)
  r.close()
"""
import os
import socket
import sys
import time

import paramiko

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    with open(os.path.join(SCRIPT_DIR, "config.json"), "r", encoding="utf-8") as f:
        return json_load(f)


def json_load(f):
    import json
    return json.load(f)


class RemoteError(Exception):
    pass


class Remote:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        self.client = None

    def connect(self):
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(self.cfg["host"], username=self.cfg["user"],
                      password=self.cfg["password"], timeout=20)
        except Exception as e:  # noqa: BLE001 - 统一转成 RemoteError 向上抛
            raise RemoteError(f"连接失败 {self.cfg['host']}: {e}")
        self.client = c
        return self

    def _ensure(self):
        if not self.client:
            self.connect()

    def exec(self, cmd, timeout=300):
        """执行远程命令，返回 (rc, stdout, stderr)。"""
        self._ensure()
        _, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    def exec_detach(self, cmd):
        """后台执行长任务并立即返回，不等待输出。

        解决坑位 7：`stdout.read()` 在后台 nohup 进程持有 channel 时阻塞 30s 抛
        PipeTimeout。这里 open session 执行命令后立刻 close，根本不读输出——
        后台进程用 `setsid nohup ... & disown` 脱离会话，channel 关闭不影响它。
        """
        self._ensure()
        transport = self.client.get_transport()
        if transport is None:
            raise RemoteError("SSH transport 不可用")
        chan = transport.open_session()
        chan.exec_command(cmd)
        chan.close()
        return 0, "started", ""

    def exec_stdin(self, cmd, data, timeout=120):
        """执行远程命令并写入 stdin（用于 docker exec -i python - 传脚本）。"""
        self._ensure()
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        stdin.write(data)
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err

    def upload(self, local, remote, retries=3):
        """SFTP 上传本地文件到服务器；连接中断时重连并重试（最多 retries 次）。

        2026-08-25 曾连续两次在 21MB tarball 上传中段断开（paramiko EOFError，
        服务器 auth.log 无主动断开记录，疑为到腾讯云的链路对大流量不稳定）。
        此处对传输中断（EOFError/SSHException/OSError/socket.error）重连重试，
        重试前先清理远端残缺文件，指数退避（5s/10s）。
        """
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                self._ensure()
                sftp = self.client.open_sftp()
                try:
                    try:
                        sftp.remove(remote)  # 清掉上次中断留下的残缺文件
                    except OSError:
                        pass
                    sftp.put(local, remote)
                finally:
                    sftp.close()
                return
            except (EOFError, paramiko.SSHException, OSError, socket.error) as e:
                last_exc = e
                try:
                    if self.client:
                        self.client.close()
                except Exception:  # noqa: BLE001 - 关闭旧连接失败不影响重试
                    pass
                self.client = None
                if attempt >= retries:
                    break
                time.sleep(5 * attempt)
        raise RemoteError(f"上传 {local} 失败（已重试 {retries} 次）: {last_exc}")

    def close(self):
        if self.client:
            self.client.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    r = Remote()
    r.connect()
    try:
        if sys.argv[1] == "upload":
            local = sys.argv[2]
            name = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(local)
            r.upload(local, f"/home/ubuntu/{name}")
            print(f"uploaded {name}")
        else:
            cmd = sys.argv[1]
            timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 300
            rc, out, err = r.exec(cmd, timeout=timeout)
            if out:
                sys.stdout.write(out)
            if err:
                sys.stderr.write("STDERR: " + err)
            print(f"RC={rc}")
            sys.exit(0 if rc == 0 else 1)
    finally:
        r.close()
