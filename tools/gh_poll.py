#!/usr/bin/env python
"""Poll the pending device code in config/_device.json until the user authorises it."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "config" / "_device.json"
TOKEN = ROOT / "config" / "github.token"
CLIENT_ID = "178c6fc778ccc68e1d6a"


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
        try:
            return e.code, json.loads(e.read())
        except Exception:  # noqa: BLE001
            return e.code, {}


def main():
    dev = json.loads(DEV.read_text())
    deadline = time.time() + 780
    interval = max(int(dev.get("interval", 5)), 5)
    while time.time() < deadline:
        time.sleep(interval)
        code, tok = post("https://github.com/login/oauth/access_token", {
            "client_id": CLIENT_ID,
            "device_code": dev["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        err = tok.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err == "expired_token":
            print("device code expired", flush=True)
            return 1
        if err:
            print("error:", err, tok.get("error_description", ""), flush=True)
            return 1
        token = tok.get("access_token")
        if token:
            TOKEN.write_text(token + "\n", encoding="utf-8")
            print("TOKEN_OK scope=" + tok.get("scope", ""), flush=True)
            return 0
    print("timeout", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
