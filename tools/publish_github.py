#!/usr/bin/env python
"""Create the GitHub repo, push main and publish a Release with the APK.

Token is read from config/github.token (first line) or GITHUB_TOKEN.
Proxy is taken from HTTPS_PROXY / HTTP_PROXY.

  python tools/publish_github.py            # full run
  python tools/publish_github.py --dry-run  # only verify token, print login
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "config" / "github.token"
REPO_NAME = "IndexTranslate_OnXiaomi"
DESCRIPTION = (
    "Fully offline real-time Chinese→English subtitle overlay for Android "
    "(Termux + CrispASR + Index-Echo-2B). 小米15 本地实时中英字幕悬浮窗。"
)
APK = ROOT / "release" / "ITX-Subtitle-1.2.apk"
TAG = "v1.2"
RELEASE_TITLE = "v1.2 — 中英双向互译 / bilingual zh<->en"
RELEASE_BODY = """## 中文

小米 15（Android 16 / HyperOS）上验证通过的**本地实时中英字幕悬浮窗**。

- 中英双向：说中文出英文大字+中文小字，说英文出中文大字+英文小字\n- 上一句与当前句同样式，长句可各自换行
- 全屏纯白悬浮窗，浮于其他 App 之上，无需 root
- 模型 index-echo-2b Q8 常驻手机，全程离线
- 一句说完约 3–7 秒出字（2B 模型 CPU 推理上限）

**安装**：下载 `ITX-Subtitle-1.0.apk` 安装，然后按 [README](README.md) 授权两个权限
（`SYSTEM_ALERT_WINDOW` 与 `RECORD_AUDIO` 的 appop，缺一不可），
再按 [docs/deploy.md](docs/deploy.md) 在 Termux 里装好模型与 CrispASR。

**使用**：`bash ~/itx/start.sh`（会自动拉起 App），点「退出」结束。

## English

Offline, on-device real-time zh<->en subtitle overlay verified on Xiaomi 15
(Android 16 / HyperOS). Chinese speech → large English text + small Chinese reference line,
previous sentence keeps the same style, full-screen white overlay above other apps, no root required.

Install the APK, grant the two permissions described in the README, follow `docs/deploy.md`
to set up Termux + model + CrispASR, then run `bash ~/itx/start.sh`.
"""


def token() -> str:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"].strip()
    if TOKEN_FILE.is_file():
        for line in TOKEN_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    sys.exit("no token: put it in config/github.token or set GITHUB_TOKEN")


def api(method, path, tok, data=None, base="https://api.github.com"):
    body = None
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "itx-publish",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw[:300]}


def git(*args, check=True):
    env = dict(os.environ)
    r = subprocess.run(["git", "-C", str(ROOT), "-c", "http.sslBackend=openssl", *args],
                       capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args[:2])} failed:\n{r.stderr[-800:]}")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repo", default=REPO_NAME)
    a = ap.parse_args()

    tok = token()
    code, me = api("GET", "/user", tok)
    if code != 200:
        sys.exit(f"token rejected ({code}): {me}")
    login = me["login"]
    print(f"token ok, user = {login}")

    code, repo = api("GET", f"/repos/{login}/{a.repo}", tok)
    if code == 200:
        print(f"repo exists: {repo['html_url']}")
    else:
        code, repo = api("POST", "/user/repos", tok, {
            "name": a.repo,
            "description": DESCRIPTION,
            "private": False,
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        })
        if code not in (200, 201):
            sys.exit(f"create repo failed ({code}): {repo}")
        print(f"repo created: {repo['html_url']}")

    if a.dry_run:
        print("dry-run: stopping before push")
        return 0

    url = f"https://x-access-token:{tok}@github.com/{login}/{a.repo}.git"
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", url)
    print("pushing main ...")
    r = git("push", "-u", "origin", "main", check=False)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        sys.exit("push failed")
    print("pushed")

    code, rel = api("GET", f"/repos/{login}/{a.repo}/releases/tags/{TAG}", tok)
    if code == 200:
        print(f"release {TAG} exists: {rel['html_url']}")
    else:
        code, rel = api("POST", f"/repos/{login}/{a.repo}/releases", tok, {
            "tag_name": TAG,
            "name": RELEASE_TITLE,
            "body": RELEASE_BODY,
            "draft": False,
            "prerelease": False,
        })
        if code not in (200, 201):
            sys.exit(f"create release failed ({code}): {rel}")
        print(f"release created: {rel['html_url']}")

    upload_url = rel["upload_url"].split("{")[0]
    asset_name = APK.name
    data = APK.read_bytes()
    req = urllib.request.Request(
        f"{upload_url}?name={asset_name}",
        data=data,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "itx-publish",
            "Content-Type": "application/vnd.android.package-archive",
            "Content-Length": str(len(data)),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            asset = json.loads(r.read())
        print(f"asset uploaded: {asset['browser_download_url']}")
    except urllib.error.HTTPError as e:
        print("asset upload failed:", e.code, e.read()[:300])

    print(f"done: {repo['html_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
