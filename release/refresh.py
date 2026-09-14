# -*- coding: utf-8 -*-
"""
覆盖已发布 Release 上的产物（同名替换）。

publish.py 遇到同名资产会**跳过**（它假设你只发新版本）。改完 bug 想原地
替换安装包时，必须先 DELETE 掉旧资产再重新上传 —— 这个脚本干这件事。

Token 同样走 `git credential fill`，全程不打印、不落盘。
"""
import subprocess
import sys
import time
from pathlib import Path

import httpx

# Windows 控制台默认 GBK，打印 ✅ 会抛 UnicodeEncodeError（项目老坑）
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = "Tambacy/xk"
TAG = "v0.2.0"
ROOT = Path(r"E:\Test_Project")
NOTES = ROOT / "release" / "RELEASE_NOTES.md"
ASSETS = [
    ROOT / "release" / "XkHelper-v0.2.0-source.zip",
    ROOT / "xk_app" / "installer" / "XkHelper-Setup-0.2.0.exe",
]


def get_token() -> str | None:
    try:
        p = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=30)
    except Exception as e:
        print("  取凭证失败:", type(e).__name__)
        return None
    for line in (p.stdout or "").splitlines():
        if line.startswith("password="):
            return line[len("password="):].strip()
    return None


def main():
    print("=" * 66)
    print(f"覆盖 {TAG} 的发布产物")
    print("=" * 66)

    missing = [p for p in ASSETS if not p.exists()]
    if missing:
        for p in missing:
            print(f"  ❌ 缺少产物：{p}")
        return 1

    token = get_token()
    if not token:
        print("  ❌ 没能从凭证管理器取到 token")
        return 1
    print(f"  ✅ 已取到 token（{len(token)} 字符，未显示）")

    H = {"Authorization": f"Bearer {token}",
         "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    api = f"https://api.github.com/repos/{REPO}"

    with httpx.Client(timeout=60, headers=H, follow_redirects=True) as c:
        me = c.get("https://api.github.com/user")
        if me.status_code != 200:
            print(f"  ❌ token 无效：{me.status_code} {me.text[:120]}")
            return 1
        print(f"  身份: {me.json().get('login')}")

        rel = c.get(f"{api}/releases/tags/{TAG}")
        if rel.status_code != 200:
            print(f"  ❌ 找不到 Release {TAG}：{rel.status_code}")
            return 1
        r = rel.json()
        rid = r["id"]

        # 顺便刷新说明
        if NOTES.exists():
            body = NOTES.read_text(encoding="utf-8")
            pr = c.patch(f"{api}/releases/{rid}", json={"body": body})
            print(f"  {'✅' if pr.status_code == 200 else '⚠️ '} 说明已更新（{pr.status_code}）")

        # 删掉同名旧资产
        want = {p.name for p in ASSETS}
        for a in r.get("assets", []):
            if a["name"] in want:
                d = c.delete(f"{api}/releases/assets/{a['id']}")
                mb = a["size"] / 1024 / 1024
                print(f"  🗑  删除旧 {a['name']}（{mb:.1f} MB）-> {d.status_code}")

        # 上传新资产
        up = f"https://uploads.github.com/repos/{REPO}/releases/{rid}/assets"
        for path in ASSETS:
            size_mb = path.stat().st_size / 1024 / 1024
            print(f"  ⬆ 上传 {path.name}（{size_mb:.1f} MB）…")
            t0 = time.perf_counter()
            try:
                with open(path, "rb") as fh:
                    resp = c.post(up, params={"name": path.name}, content=fh,
                                  headers={"Content-Type": "application/octet-stream"},
                                  timeout=httpx.Timeout(900.0, connect=60.0))
            except Exception as e:
                print(f"     ❌ 上传异常：{type(e).__name__}: {str(e)[:150]}")
                return 1
            dt = time.perf_counter() - t0
            if resp.status_code in (200, 201):
                speed = size_mb / dt if dt > 0 else 0
                print(f"     ✅ 完成，用时 {dt:.0f}s（{speed:.1f} MB/s）")
            else:
                print(f"     ❌ {resp.status_code} {resp.text[:200]}")
                return 1

        final = c.get(f"{api}/releases/tags/{TAG}").json()
        print()
        print("=" * 66)
        print(f"发布页: {final['html_url']}")
        print("产物:")
        for a in final.get("assets", []):
            print(f"  {a['name']:<42} {a['size']/1024/1024:>7.1f} MB  "
                  f"下载 {a['download_count']} 次")
        print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
