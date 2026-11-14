#!/usr/bin/env python
"""Verify the published repo: metadata, file list, release asset, secret-leak check."""
import json
import urllib.request

OWNER = "Baizhi-Angelica"
NAME = "IndexTranslate_OnXiaomi"
tok = open("config/github.token").read().strip()


def api(path):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "itx-verify",
    })
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


repo = api(f"/repos/{OWNER}/{NAME}")
print("repo:", repo["full_name"], "| private:", repo["private"], "| default:", repo["default_branch"])
print("desc:", (repo["description"] or "")[:80])
tree = api(f"/repos/{OWNER}/{NAME}/git/trees/{repo['default_branch']}?recursive=1")
paths = sorted(x["path"] for x in tree["tree"] if x["type"] == "blob")
print("files:", len(paths))
for p in paths:
    print("  ", p)

rel = api(f"/repos/{OWNER}/{NAME}/releases/tags/v1.3")
print("release:", rel["tag_name"], "|", rel["name"][:50])
for a in rel["assets"]:
    print("  asset:", a["name"], a["size"], "bytes")
    print("  url:", a["browser_download_url"])

leak = [p for p in paths if p.endswith("phone.env") or "token" in p.lower()
        or p.endswith((".keystore", ".jks", ".pem"))]
print("secret-ish files in repo:", leak or "none")
