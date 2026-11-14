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
APK = ROOT / "release" / "ITX-Subtitle-1.3.apk"
TAG = "v1.3"
RELEASE_TITLE = "v1.3 — 中文不再被误判成英文 / code-switch fix"
RELEASE_BODY = """## 中文

小米 15（Android 16 / HyperOS）上验证通过的**本地实时中英字幕悬浮窗**。

本版修复：

- **中文被误判成英文**：模型会先写转写、再按"第 1 行有没有汉字"决定译文方向，不再让模型自己猜语种。
  实测 61 条真实字幕里 26 条没有译文，现在 35 条 TTS 回归只剩 1 条 0.3 秒的"嗯。"没译文，且与音色无关。
- **持续说话优先显示最新一句**：模型追不上时队列只保留最新 3 段，满了丢最旧的，不会攒出十几秒前的字幕。
- **单次输出上限 160 tokens**：防止解码跑飞拖几十秒。
- **App 断连不再空转**：引擎断开时保持录音对象并低频率重连，CPU 从 62% 降到约 3.5%，
  引擎重启后录音自动恢复；`stop.sh` 会 force-stop App，真正释放麦克风。

**更新方式**：下载 `ITX-Subtitle-1.3.apk` 覆盖安装；引擎侧（`live.py` / `stop.sh`）重跑
`bash ~/itx-src/tools/bootstrap_phone.sh` 即可（脚本幂等）。

**使用**：`bash ~/itx/start.sh`（会自动拉起 App），点「退出」结束。

## English

Offline, on-device real-time zh<->en subtitle overlay verified on Xiaomi 15
(Android 16 / HyperOS).

What changed in 1.3:

- Translation direction is anchored on the transcript line ("Chinese characters
  in line 1 -> line 2 must be English"), so Chinese speech is no longer
  mistaken for English and left untranslated.
- Under continuous speech the queue keeps only the newest three segments and
  drops the oldest, so captions never trail tens of seconds behind.
- A 160-token cap per request stops a runaway decode.
- The overlay app no longer busy-spins when the engine dies (62% -> ~3.5% CPU)
  and resumes recording automatically after the engine comes back.

Install `ITX-Subtitle-1.3.apk`; re-run `bash ~/itx-src/tools/bootstrap_phone.sh`
to update the Termux side, then `bash ~/itx/start.sh`.
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
