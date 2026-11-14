#!/usr/bin/env python
"""Tiny SSH helper for the Android/Termux target device.

Connection settings are read from (in order of precedence):
  1. environment variables  PHONE_HOST / PHONE_PORT / PHONE_USER / PHONE_PASS
  2. the file config/phone.env   (KEY=VALUE lines, git-ignored)

Usage:
  python phone.py "command in termux bash"
  python phone.py -s "command executed as root via su -c"
  python phone.py -t 60 "cmd"                       # timeout seconds (default 120)
  python phone.py --put LOCAL REMOTE                # upload a file (binary safe)
  python phone.py --get REMOTE LOCAL                # download a file
  echo bytes | python phone.py -u /remote/path      # upload stdin
  python phone.py -d /remote/file -o local.bin      # download to stdout/file
"""
import argparse
import os
import shlex
import sys
import time
from pathlib import Path

import paramiko

HERE = Path(__file__).resolve().parent
DEFAULT_ENV = HERE.parent / "config" / "phone.env"


def load_config() -> dict:
    cfg = {}
    env_file = Path(os.environ.get("PHONE_ENV", DEFAULT_ENV))
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("PHONE_HOST", "PHONE_PORT", "PHONE_USER", "PHONE_PASS"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def connect(cfg, timeout=15):
    missing = [k for k in ("PHONE_HOST", "PHONE_USER", "PHONE_PASS") if not cfg.get(k)]
    if missing:
        sys.exit(
            "missing connection settings: " + ", ".join(missing)
            + "\ncreate config/phone.env (see config/phone.env.example) or set env vars"
        )
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        cfg["PHONE_HOST"],
        port=int(cfg.get("PHONE_PORT", "8022")),
        username=cfg["PHONE_USER"],
        password=cfg["PHONE_PASS"],
        timeout=timeout,
        banner_timeout=30,
        auth_timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="*", help="command to run")
    ap.add_argument("-s", "--su", action="store_true", help="run via su -c '...'")
    ap.add_argument("-t", "--timeout", type=float, default=120.0)
    ap.add_argument("-u", "--upload", metavar="REMOTE")
    ap.add_argument("-d", "--download", metavar="REMOTE")
    ap.add_argument("-o", "--out", metavar="LOCAL")
    ap.add_argument("--put", nargs=2, metavar=("LOCAL", "REMOTE"), help="upload a local file")
    ap.add_argument("--get", nargs=2, metavar=("REMOTE", "LOCAL"), help="download a remote file")
    a = ap.parse_args()

    cfg = load_config()
    cli = connect(cfg)
    try:
        if a.put:
            local, remote = a.put
            sftp = cli.open_sftp()
            sftp.put(local, remote)
            sftp.close()
            print(f"put {local} -> {remote}")
            return 0
        if a.get:
            remote, local = a.get
            sftp = cli.open_sftp()
            sftp.get(remote, local)
            sftp.close()
            print(f"got {remote} -> {local}")
            return 0
        if a.upload:
            data = sys.stdin.buffer.read()
            sftp = cli.open_sftp()
            with sftp.file(a.upload, "wb") as f:
                f.write(data)
            sftp.close()
            print(f"uploaded {len(data)} bytes -> {a.upload}")
            return 0
        if a.download:
            sftp = cli.open_sftp()
            with sftp.file(a.download, "rb") as f:
                data = f.read()
            sftp.close()
            if a.out:
                with open(a.out, "wb") as f:
                    f.write(data)
                print(f"downloaded {len(data)} bytes -> {a.out}")
            else:
                sys.stdout.buffer.write(data)
            return 0

        cmd = " ".join(a.cmd) if a.cmd else sys.stdin.read()
        if a.su:
            cmd = "su -c " + shlex.quote(cmd)
        chan = cli.get_transport().open_session()
        chan.settimeout(a.timeout)
        chan.exec_command(cmd)
        out, err = b"", b""
        deadline = time.time() + a.timeout
        while True:
            if chan.recv_ready():
                out += chan.recv(65536)
            if chan.recv_stderr_ready():
                err += chan.recv_stderr(65536)
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            if time.time() > deadline:
                chan.close()
                sys.stdout.buffer.write(out)
                sys.stderr.buffer.write(err)
                print(f"\n[timeout after {a.timeout}s]", file=sys.stderr)
                return 124
            time.sleep(0.02)
        rc = chan.recv_exit_status()
        chan.close()
        sys.stdout.buffer.write(out)
        sys.stderr.buffer.write(err)
        return rc
    finally:
        cli.close()


if __name__ == "__main__":
    sys.exit(main())
