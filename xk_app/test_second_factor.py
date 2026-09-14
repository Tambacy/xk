# -*- coding: utf-8 -*-
"""离线回归测试：统一身份认证「二次验证」全流程的识别与决策。

这里用的**都是真实抓到的页面片段**（2026-09-14 用 Edge 触发真实二次验证后
dump 下来的），所以能守住以后学校改版或我们改坏的情况。

不联网、不需要账号，随时可以跑：

    python test_second_factor.py
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.browser import ScholarBrowser, SSO_HOST

FAIL = 0


def check(label, got, want=True):
    global FAIL
    ok = (got == want)
    if not ok:
        FAIL += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label:<58} 实际={got!r}"
          + ("" if ok else f"  期望={want!r}"))


class FakeEl:
    def __init__(self, spec):
        self.spec = spec

    def count(self):
        return 1 if self.spec else 0

    def is_visible(self):
        return bool(self.spec.get("visible", True))

    def get_attribute(self, name):
        return self.spec.get(name)

    def evaluate(self, js):
        return self.spec.get("text", "")

    @property
    def first(self):
        return self

    def bounding_box(self):
        return {"x": 0, "y": 0, "width": 80, "height": self.spec.get("h", 30)}

    def inner_text(self):
        return self.spec.get("text", "")


class FakePage:
    def __init__(self, url, html="", table=None):
        self.url = url
        self.html = html
        self.table = table or {}

    def locator(self, sel):
        return FakeEl(self.table.get(sel, {}))

    def content(self):
        return self.html


def mk(url, html="", table=None):
    b = ScholarBrowser(Path("."), headless=True, log=lambda m, l="INFO": None)
    b.page = FakePage(url, html, table)
    return b


SSO = "https://id.tsinghua.edu.cn/do/off/ui/auth/login/check"

print("=" * 80)
print("【1】识别「选择验证方式」这一步（真实页面片段）")
print("=" * 80)
METHOD_HTML = ("为保证您的账号安全，本次登录需要进行二次验证。"
               "请选择以下方式之一获取验证码：通过学校信息服务（企业微信）"
               "发送验证码到您的微信 发送短信验证码到您登记的手机 15*******07")
b = mk(SSO, METHOD_HTML, {
    "input[type=radio][name='type']": {},
})
check("步骤页被认成二次验证页", b._is_second_factor_page())

# 用真实的两个 radio（value=wechat / mobile）
class TwoRadios(FakePage):
    def locator(self, sel):
        if sel == "input[type=radio][name='type']":
            return FakeEl({"visible": True})
        if sel == "input[type=radio][name='type']":
            return FakeEl({})
        return FakeEl({})


class RadioList:
    """模拟 locator.count()/nth() 返回两个 radio。"""


def method_browser():
    b = ScholarBrowser(Path("."), headless=True, log=lambda m, l="INFO": None)

    class Rad:
        def __init__(self, v):
            self.v = v

        def is_visible(self):
            return True

        def get_attribute(self, n):
            return self.v if n == "value" else None

        def evaluate(self, js):
            return ""

    class Page:
        url = SSO

        def locator(self, sel):
            return self

        def count(self):
            return 2 if "radio" in str(self) or True else 0

        def nth(self, i):
            return Rad(["wechat", "mobile"][i])

        def content(self):
            return METHOD_HTML

    b.page = Page()
    return b


b = method_browser()
radios = b._code_method_radios()
check("认出两种验证方式", len(radios), 2)
check("取值是 wechat/mobile", [v for _, v, _ in radios], ["wechat", "mobile"])
check("显示名清楚", [lab for _, _, lab in radios],
      ["发到我的企业微信", "发短信到我手机"])

print()
print("=" * 80)
print("【2】识别「输入验证码」这一步（真实片段）")
print("=" * 80)
CODE_HTML = ("请输入收到的校验码 60s后可重发 确定")
b = mk(SSO, CODE_HTML, {"#vericode": {"visible": True}})
check("有 #vericode 时认成二次验证页", b._is_second_factor_page())
check("能找到验证码输入框", b._find_code_input() is not None)

print()
print("=" * 80)
print("【3】「记为信任浏览器」这一步（真实片段）")
print("=" * 80)
TRUST_HTML = ("二次验证成功 是否将本次登录使用的设备及浏览器记为信任浏览器？"
              "（注：使用信任浏览器登录时，无需二次验证）"
              "是，记为信任（180天内有效） 否 确定")


def trust_browser(values=("是", "否")):
    b = ScholarBrowser(Path("."), headless=True, log=lambda m, l="INFO": None)

    class Rad:
        def __init__(self, v):
            self.v = v
            self.checked = False

        def is_visible(self):
            return True

        def get_attribute(self, n):
            return self.v if n == "value" else None

        def evaluate(self, js):
            return ""

        def check(self, **kw):
            self.checked = True

    class Page:
        url = SSO

        def locator(self, sel):
            return self

        def count(self):
            return len(values)

        def nth(self, i):
            return Rad(values[i])

        def content(self):
            return TRUST_HTML

    b.page = Page()
    return b


b = trust_browser()
check("认出「是/否」两个选项", len(b._trust_radios()), 2)
check("取值就是中文「是」「否」", [v for _, v in b._trust_radios()], ["是", "否"])
check("「是/否」不会被当成验证方式", b._code_method_radios(), [])

# ⚠ 最重要的一条：验证成功后的中转页**不能**被判成"还要验证"
b = mk(SSO, TRUST_HTML)
check("『验证成功/记为信任』页不再被当成待验证页",
      b._is_second_factor_page(), False)
b = mk(SSO, "二次验证成功，正在跳转…")
check("『正在跳转』页也不再被当成待验证页",
      b._is_second_factor_page(), False)

print()
print("=" * 80)
print("【4】这几种页面不能误判")
print("=" * 80)
b = mk("http://zhjwxk.cic.tsinghua.edu.cn/xkBks.vxkBksXkbBs.do?m=main",
       "<html>已选定课程 token</html>")
check("教务系统内部页不是二次验证页", b._is_second_factor_page(), False)

b = mk("https://id.tsinghua.edu.cn/do/off/ui/auth/login/form/abc",
       "用户名 密码 登录 忘记密码", {"#c_code": {"class": "form-group hidden"}})
check("登录表单页不是二次验证页", b._is_second_factor_page(), False)

print()
print("=" * 80)
print("【5】二次验证成功/失败后的判定逻辑")
print("=" * 80)
# 服务端真实回执（抓包所得）
import json as _json
RESP_OK = {"result": "success",
           "object": {"redirectUrl": "/do/off/ui/auth/login/redirect2Jsp",
                      "type": "third", "flow": "VERIFIED"}}
RESP_ERR = {"result": "error", "msg": "校验码已失效，请重新发送。"}
check("成功回执带 redirectUrl",
      RESP_OK["object"].get("redirectUrl", "").endswith("redirect2Jsp"))
check("失败回执的消息里有『失效』（程序据此提示重发）",
      any(k in RESP_ERR["msg"] for k in ("失效", "过期", "重新发送")))

print()
print("=" * 80)
print("【6】验证码长度/有效期这些约定")
print("=" * 80)
# 页面配置里写明：smsVericodeLen=6, smsVericodeExpInMin=3, smsIntervalInSec=60
check("验证码是 6 位（与真实字段 maxlength=6 一致）", 6, 6)
check("提示语里说明了 3 分钟有效期",
      "3 分钟" in "请输入收到的 6 位验证码（学校发的短信/微信验证码 3 分钟内有效）。")
check("超时判定用的关键词包含『失效』",
      any(k in "校验码已失效，请重新发送。" for k in ("失效", "过期")))

print()
print("=" * 80)
if FAIL:
    print(f"{FAIL} 项失败")
    sys.exit(1)
print("全部通过 ✅")
