# -*- coding: utf-8 -*-
"""
凭据的本地安全存储
==================

**绝不明文落盘。** 用 Windows 自带的 DPAPI（CryptProtectData）加密，
密钥由操作系统按"当前用户 + 当前机器"派生：

  * 换个用户账户登录同一台电脑 → 解不开
  * 把文件拷到别的电脑 → 解不开
  * 不需要我们自己的密钥，也就不存在"密钥和密文放一起"的问题

如果 DPAPI 不可用，**宁可拒绝保存**，也不会退回明文。

另外提供全局的敏感信息脱敏表：登录成功后把密码、Cookie、密文登记进来，
任何写进日志的文本都会被自动替换成 ***，避免"日志里泄密"这种低级事故。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path


# --------------------------------------------------------------------------
# Windows DPAPI
# --------------------------------------------------------------------------

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_from_bytes(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _bytes_from_blob(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def dpapi_protect(data: bytes, entropy: bytes = b"XkHelper") -> bytes:
    """把数据加密成只有当前用户能解开的密文。"""
    if not _dpapi_available():
        raise RuntimeError("当前系统不支持 DPAPI")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = _blob_from_bytes(data)
    blob_ent = _blob_from_bytes(entropy)
    blob_out = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in), "XkHelper credentials", ctypes.byref(blob_ent),
        None, None, 0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out))
    if not ok:
        raise RuntimeError(f"CryptProtectData 失败，错误码 {ctypes.get_last_error()}")
    try:
        return _bytes_from_blob(blob_out)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def dpapi_unprotect(data: bytes, entropy: bytes = b"XkHelper") -> bytes:
    if not _dpapi_available():
        raise RuntimeError("当前系统不支持 DPAPI")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = _blob_from_bytes(data)
    blob_ent = _blob_from_bytes(entropy)
    blob_out = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, ctypes.byref(blob_ent),
        None, None, 0x01, ctypes.byref(blob_out))
    if not ok:
        raise RuntimeError("CryptUnprotectData 失败（可能是换了用户或换了电脑）")
    try:
        return _bytes_from_blob(blob_out)
    finally:
        kernel32.LocalFree(blob_out.pbData)


# --------------------------------------------------------------------------
# 凭据仓库
# --------------------------------------------------------------------------

class SecretStore:
    """账号密码的加密存储。"""

    VERSION = 1

    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "credentials.dat"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return _dpapi_available()

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, user: str, password: str, *, remember: bool = True) -> tuple[bool, str]:
        """保存凭据。返回 (是否成功, 说明)。"""
        if not self.available:
            return False, "当前系统不支持加密存储，出于安全考虑不会保存密码。"
        payload = json.dumps({
            "v": self.VERSION,
            "user": user,
            "pass": password if remember else "",
            "remember": bool(remember),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False).encode("utf-8")
        try:
            blob = dpapi_protect(payload)
        except Exception as e:
            return False, f"加密失败：{e}"
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_bytes(blob)
            os.replace(tmp, self.path)      # 原子替换，避免写一半坏了
        except Exception as e:
            return False, f"写入失败：{e}"
        try:
            os.chmod(self.path, 0o600)
        except Exception:
            pass
        return True, "已加密保存（仅本机本账户可解密）"

    def load(self) -> dict:
        """读回凭据。读不出就返回空 dict。"""
        if not self.path.exists():
            return {}
        try:
            raw = dpapi_unprotect(self.path.read_bytes())
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def clear(self) -> bool:
        try:
            if self.path.exists():
                self.path.unlink()
            return True
        except Exception:
            return False

    def describe(self) -> str:
        if not self.exists():
            return "未保存"
        d = self.load()
        if not d:
            return "已保存但无法解密（换了用户或电脑）"
        u = d.get("user", "")
        masked = (u[:3] + "*" * max(0, len(u) - 5) + u[-2:]) if len(u) > 5 else "*" * len(u)
        has_pwd = bool(d.get("pass"))
        return f"{masked}（{'含密码' if has_pwd else '不含密码'}，保存于 {d.get('saved_at','?')}）"


# --------------------------------------------------------------------------
# 全局脱敏表
# --------------------------------------------------------------------------

class Redactor:
    """登记敏感值，之后任何文本里的它们都会被替换掉。

    密码、Cookie、SM2 密文都登记进来，日志就不可能泄密。
    """

    def __init__(self):
        self._secrets: list[str] = []

    def add(self, *values):
        for v in values:
            if v is None:
                continue
            s = str(v)
            if len(s) >= 4 and s not in self._secrets:
                self._secrets.append(s)
        # 长的先替换，避免短的把它切成两半
        self._secrets.sort(key=len, reverse=True)

    def clear(self):
        self._secrets.clear()

    def scrub(self, text: str) -> str:
        if not text or not self._secrets:
            return text
        out = text
        for s in self._secrets:
            if s in out:
                out = out.replace(s, "***")
        return out

    @property
    def count(self) -> int:
        return len(self._secrets)


# 全局单例
redactor = Redactor()
