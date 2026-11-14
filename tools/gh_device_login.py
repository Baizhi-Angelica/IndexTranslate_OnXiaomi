#!/usr/bin/env python
"""GitHub OAuth device-flow login (same flow as `gh auth login`).

Prints a one-time code, waits for the user to authorise it in the browser, then
saves the resulting token to config/github.token (git-ignored).

  python tools/gh_device_login.py [--scope repo] [--timeout 600]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# GitHub CLI's public OAuth app client id (device flow enabled).
CLIENT_ID = "178c6fc778ccc68e1d6a"
ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "config" / "github.token"


def post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "itx-device-login",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw[:300].decode("utf-8", "replace")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", default="repo")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()

    code, dev = post("https://github.com/login/device/code",
                     {"client_id": CLIENT_ID, "scope": a.scope})
    if code != 200 or "device_code" not in dev:
        sys.exit(f"device code request failed ({code}): {dev}")

    print("=" * 60, flush=True)
    print("请在浏览器打开：", dev["verification_uri"], flush=True)
    print("输入代码：", dev["user_code"], flush=True)
    print("=" * 60, flush=True)

    interval = max(int(dev.get("interval", 5)), 5)
    deadline = time.time() + a.timeout
    device_code = dev["device_code"]
    while time.time() < deadline:
        time.sleep(interval)
        code, tok = post("https://github.com/login/oauth/access_token", {
            "client_id": CLIENT_ID,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        err = tok.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            sys.exit(f"authorisation failed: {err} {tok.get('error_description', '')}")
        token = tok.get("access_token")
        if not token:
            continue
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
        scope = tok.get("scope", "")
        print(f"ok: token saved to {TOKEN_FILE} (scope={scope})", flush=True)
        return 0
    sys.exit("timed out waiting for authorisation")


if __name__ == "__main__":
    sys.exit(main())
