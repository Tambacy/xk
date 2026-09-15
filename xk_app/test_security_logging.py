# -*- coding: utf-8 -*-
"""验证凭据加密存储与日志脱敏（不联网、不碰真实账号）。"""
import logging
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.secretstore import SecretStore, redactor, dpapi_protect, dpapi_unprotect
from app import logging_setup as LS

FAIL = 0


def check(label, got, want=True):
    global FAIL
    ok = (got == want)
    if not ok:
        FAIL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}   实际={got!r}" + ("" if ok else f"  期望={want!r}"))


def _scratch_dir() -> Path:
    """找一个真的能写的临时目录。

    系统临时目录不是总能写：某些受限/沙箱环境里 `tempfile.mkdtemp()` 建出来的
    目录会带上只给创建者、连自己都进不去的 ACL，测试会在第一步就假失败。
    所以建完先探一下可写性，不行就退到项目自己的 data/ 下。
    """
    try:
        d = Path(tempfile.mkdtemp(prefix="xk_test_"))
        probe = d / ".probe"
        probe.write_bytes(b"x")
        probe.unlink()
        return d
    except Exception:
        d = Path(__file__).parent / "data" / "sectest"
        d.mkdir(parents=True, exist_ok=True)
        return d


tmp = _scratch_dir()
print("=" * 70)
print("【1】DPAPI 加解密")
print("=" * 70)
try:
    blob = dpapi_protect(b"hello-secret-123")
    check("密文非明文", b"hello-secret-123" not in blob)
    check("能解回原文", dpapi_unprotect(blob), b"hello-secret-123")
except Exception as e:
    check(f"DPAPI 可用（{e}）", False)

print()
print("=" * 70)
print("【2】凭据仓库")
print("=" * 70)
store = SecretStore(tmp)
check("DPAPI 可用", store.available)
check("初始未保存", store.exists(), False)
ok, msg = store.save("2020000000", "MySecretPwd!2026", remember=True)
check("保存成功", ok)
print("     ", msg)
raw = store.path.read_bytes()
check("磁盘上找不到明文密码", b"MySecretPwd!2026" not in raw)
check("磁盘上找不到明文学号", b"2020000000" not in raw)
d = store.load()
check("读回学号", d.get("user"), "2020000000")
check("读回密码", d.get("pass"), "MySecretPwd!2026")
print("      描述：", store.describe())

# 篡改密文应当解不出来（而不是返回垃圾）
bad = SecretStore(tmp)
bad.path.write_bytes(raw[:-8] + b"00000000")
check("篡改后解不出（返回空）", bool(bad.load()), False)

# 不记住密码
store.save("2020000000", "xxx", remember=False)
check("不记住密码时不留密码", store.load().get("pass"), "")

print()
print("=" * 70)
print("【3】日志脱敏")
print("=" * 70)
logdir = tmp / "logs"
cfg = LS.setup_logging(logdir, level=logging.DEBUG, console=False)
log = LS.get_logger("test")
trace = LS.get_trace_logger()

redactor.clear()
redactor.add("MySecretPwd!2026", "2020000000", "JSESSIONID=ABC123XYZ", "04deadbeef")
check("脱敏表条目数", redactor.count, 4)

log.info("用户 %s 正在登录", "2020000000")
log.info("密码是 MySecretPwd!2026 请勿外泄")
log.info("Cookie: JSESSIONID=ABC123XYZ; Path=/")
trace.debug("导航到 …&token=abc 密文=04deadbeef00")
log.error("模拟报错：密码 MySecretPwd!2026 出现在异常文本里")

for h in logging.getLogger().handlers:
    h.flush()

text = (logdir / "helper.log").read_text(encoding="utf-8")
print("    业务日志内容：")
for line in text.strip().splitlines():
    print("      " + line)
check("日志里没有明文密码", "MySecretPwd!2026" in text, False)
check("日志里没有完整学号", "2020000000" in text, False)
check("日志里没有 Cookie 值", "ABC123XYZ" in text, False)
check("出现了脱敏标记", "***" in text)

ttext = (logdir / "trace.log").read_text(encoding="utf-8")
check("trace 里没有密文", "04deadbeef" in ttext, False)
check("trace 有内容", len(ttext) > 0)

print()
print("=" * 70)
print("【4】诊断包导出")
print("=" * 70)
zpath = tmp / "diag.zip"
LS.export_diagnostics(zpath, logdir,
                      config_snapshot={"user": "2020000000", "target": ["乒乓球"]},
                      extra_text="附注：密码 MySecretPwd!2026 不应出现")
check("诊断包已生成", zpath.exists())
with zipfile.ZipFile(zpath) as z:
    names = z.namelist()
    print("      内含：", names)
    envtxt = z.read("environment.txt").decode("utf-8")
    check("诊断包里的学号已脱敏", "2020000000" in envtxt, False)
    check("诊断包里的密码已脱敏", "MySecretPwd!2026" in envtxt, False)
    check("业务日志已打入包", any("helper" in n for n in names))

print()
print("=" * 70)
print("【N】向后兼容：改名不能把老用户的凭据/数据弄丢")
print("=" * 70)
# 这两条是被一次「全局字符串替换」真实弄坏过的：
#   1. DPAPI 的熵（entropy）是密钥的一部分。把旧标识换成新标识等于换了一把
#      钥匙 —— 老用户磁盘上那份 credentials.dat 直接解不开。
#   2. 数据目录改名后要能找到旧目录并搬过来。旧名常量被一并替换成新名之后，
#      「迁移」就成了把 X 搬到 X 的空操作，升级后凭据凭空「消失」。
# 这类破坏是静默的：不报错、不崩溃，只是东西读不出来了。

from app.config import (APP_DIR_NAME, OLD_APP_DIR_NAME,   # noqa: E402
                        migrate_legacy_root)
from app.secretstore import ENTROPY, LEGACY_ENTROPY       # noqa: E402

check("旧目录名与新目录名不同", OLD_APP_DIR_NAME != APP_DIR_NAME, True)
check("旧熵与新熵不同", LEGACY_ENTROPY != ENTROPY, True)

# DPAPI：用旧熵加密的数据，必须还能解开
old_blob = dpapi_protect(b"legacy-payload", entropy=LEGACY_ENTROPY)
try:
    check("用旧熵加密的数据仍能解开",
          dpapi_unprotect(old_blob), b"legacy-payload")
except Exception as e:
    print(f"      {type(e).__name__}: {e}")
    check("用旧熵加密的数据仍能解开", False, True)
check("用新熵加密的数据能解开",
      dpapi_unprotect(dpapi_protect(b"new-payload")), b"new-payload")

_m = Path(tempfile.mkdtemp())
try:
    (_m / OLD_APP_DIR_NAME).mkdir()
    (_m / OLD_APP_DIR_NAME / "credentials.dat").write_bytes(b"x")
    (_m / OLD_APP_DIR_NAME / "config.json").write_text("{}", encoding="utf-8")
    ok = migrate_legacy_root(_m)
    check("迁移返回成功", bool(ok), True)
    check("凭据搬到了新目录",
          (_m / APP_DIR_NAME / "credentials.dat").exists(), True)
    check("配置也搬过去了",
          (_m / APP_DIR_NAME / "config.json").exists(), True)
    check("旧目录已不在", (_m / OLD_APP_DIR_NAME).exists(), False)
    check("重复迁移是幂等的", bool(migrate_legacy_root(_m)), True)
finally:
    shutil.rmtree(_m, ignore_errors=True)

print()
print("=" * 70)
shutil.rmtree(tmp, ignore_errors=True)
if FAIL:
    print(f"{FAIL} 项失败")
    sys.exit(1)
print("全部通过 ✅")
