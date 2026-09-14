# -*- coding: utf-8 -*-
"""
用 GitHub API 建 Release 并上传产物。

Token 通过 `git credential fill` 从已登录的凭证管理器里取，
**全程不打印、不落盘**。
"""
import subprocess
import sys
import time
from pathlib import Path

import httpx

# Windows 控制台默认 GBK，打印 ✅ 之类的字符会直接抛 UnicodeEncodeError
# （项目里踩过的老坑，main.py / _creds.py 都补过同样的东西）
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO = "Tambacy/xk"
TAG = "v0.2.0"
NAME = "v0.2.0 二次验证走通了 + 抢课安全护栏"
ROOT = Path(r"E:\Test_Project")
NOTES = ROOT / "release" / "RELEASE_NOTES.md"
ASSETS = [
    ROOT / "release" / "XkHelper-v0.2.0-source.zip",
    ROOT / "xk_app" / "installer" / "XkHelper-Setup-0.2.0.exe",
]


def get_token() -> str | None:
    """从凭证管理器取 GitHub token（不会打印出来）。"""
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
    print(f"发布 {TAG}")
    print("=" * 66)

    token = get_token()
    if not token:
        print("  ❌ 没能从凭证管理器取到 token")
        return 1
    print(f"  ✅ 已取到 token（{len(token)} 字符，未显示）")

    H = {"Authorization": f"Bearer {token}",
         "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}

    with httpx.Client(timeout=60, headers=H, follow_redirects=True) as c:
        # 确认身份
        me = c.get("https://api.github.com/user")
        if me.status_code != 200:
            print(f"  ❌ token 无效：{me.status_code} {me.text[:120]}")
            return 1
        print(f"  身份: {me.json().get('login')}")

        body = NOTES.read_text(encoding="utf-8") if NOTES.exists() else "第一版"

        # 建或复用 release
        api = f"https://api.github.com/repos/{REPO}"
        rel = c.get(f"{api}/releases/tags/{TAG}")
        if rel.status_code == 200:
            r = rel.json()
            print(f"  Release {TAG} 已存在，复用它（id={r['id']}）")
            # 更新说明
            c.patch(f"{api}/releases/{r['id']}", json={"body": body, "name": NAME})
        else:
            resp = c.post(f"{api}/releases", json={
                "tag_name": TAG, "name": NAME, "body": body,
                "draft": False, "prerelease": False,
            })
            if resp.status_code not in (200, 201):
                print(f"  ❌ 建 Release 失败：{resp.status_code} {resp.text[:300]}")
                return 1
            r = resp.json()
            print(f"  ✅ Release 已创建: {r['html_url']}")

        rid = r["id"]
        existing = {a["name"] for a in r.get("assets", [])}

        # 上传产物
        for path in ASSETS:
            if not path.exists():
                print(f"  ⚠️ 找不到 {path.name}，跳过")
                continue
            size_mb = path.stat().st_size / 1024 / 1024
            if path.name in existing:
                print(f"  ⏭  {path.name} 已存在，跳过")
                continue
            print(f"  ⬆ 上传 {path.name}（{size_mb:.1f} MB）…")
            t0 = time.perf_counter()
            up = f"https://uploads.github.com/repos/{REPO}/releases/{rid}/assets"
            try:
                with open(path, "rb") as fh:
                    resp = c.post(
                        up, params={"name": path.name},
                        content=fh,
                        headers={"Content-Type": "application/octet-stream"},
                        timeout=httpx.Timeout(600.0, connect=60.0))
            except Exception as e:
                print(f"     ❌ 上传异常：{type(e).__name__}: {str(e)[:150]}")
                continue
            dt = time.perf_counter() - t0
            if resp.status_code in (200, 201):
                speed = size_mb / dt if dt > 0 else 0
                print(f"     ✅ 完成，用时 {dt:.0f}s（{speed:.1f} MB/s）")
            else:
                print(f"     ❌ {resp.status_code} {resp.text[:200]}")

        # 收尾：列出最终产物
        final = c.get(f"{api}/releases/tags/{TAG}").json()
        print()
        print("=" * 66)
        print(f"发布页: {final['html_url']}")
        print("产物:")
        for a in final.get("assets", []):
            print(f"  {a['name']:<42} {a['size']/1024/1024:>7.1f} MB  下载 {a['download_count']} 次")
        print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
