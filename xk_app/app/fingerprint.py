# -*- coding: utf-8 -*-
"""浏览器身份一致性
==================

只解决一件事：**让 navigator.userAgentData 的品牌列表看起来是真正的
Google Chrome，而不是「一个 Chromium」。**

为什么必须修
------------
随包的是 Playwright 自带的 Chromium。实测它的品牌列表是：

    Chromium 151 | Not=A?Brand 99

而同一台机器上真正的 Chrome / Edge 是：

    Google Chrome 153   | Not_A Brand 8 | Chromium 153
    Microsoft Edge 153  | Not_A Brand 8 | Chromium 153

**一个正常用户不可能只报 "Chromium"。** 要么 Chrome、要么 Edge、要么
Firefox/Safari。只有「Chromium 内核的衍生浏览器 / 嵌入式浏览器 / 自动化
框架」才会给出这种品牌组合。查这个只要一行 JS，而且是 Cloudflare、
Akamai 这类风控 SDK 的默认检查项。

为什么用 CDP 而不是 add_init_script
-----------------------------------
在页面里 `Object.defineProperty(navigator, 'userAgentData', ...)` 是**改 JS
对象**：原型上的原生 getter 被替换掉了，对方一个
`Object.getOwnPropertyDescriptor(Navigator.prototype, 'userAgentData')`
或 `Function.prototype.toString.call(...)` 就能看出是伪造的。

`Emulation.setUserAgentOverride` 是**浏览器进程层面**的覆写：渲染器里
`navigator.userAgentData` 仍然是原生 getter，只是它返回的数据变了。
实测 `descriptor.getNative === true`、brands 的 getter 也是原生的、
原型仍是 `NavigatorUAData`，JS 侧查不出任何痕迹。

不做多余的伪装
--------------
有头模式下浏览器本来就没有别的破绽（插件 5 个、chrome.app 在、GPU 是真的、
专有编解码器支持、无 cdc_ 残留），所以这里**只修品牌一项**。
伪装越多，自相矛盾的机会越多。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# 真 Chrome 在 Windows 上的品牌形状（实测自本机 Chrome 153）
CHROME_BRAND = "Google Chrome"
GREASE_BRAND = "Not_A Brand"
GREASE_VERSION = "8"
GREASE_FULL = "8.0.0.0"

PLATFORM = "Windows"
ARCHITECTURE = "x86"
BITNESS = "64"
ACCEPT_LANGUAGE = "zh-CN,zh"
# 注意：这里**只能写纯语言标签，不能写成 Accept-Language 请求头的形式**。
#
# CDP 的 Emulation.setUserAgentOverride.acceptLanguage 会被 Chromium 同时
# 用在两个地方：
#   1) Accept-Language 请求头 —— Chromium 会**自己再加一遍 q 值**
#   2) navigator.languages  —— 原样按逗号切开，不做任何解析
#
# 所以如果写成 "zh-CN,zh;q=0.9,en;q=0.8"（看着更"标准"），实际结果是：
#   请求头 = zh-CN,zh;q=0.9;q=0.9,en;q=0.8;q=0.8   <- q 值重复，语法不合法
#   navigator.languages = ["zh-CN","zh;q=0.9","en;q=0.8"]  <- 标签里带 ;q=
# 两个都是真机绝不会出现的值（已对着正常启动的 Chrome 153 实测对照过）。
#
# 写成 "zh-CN,zh" 之后两边都对上真机：
#   请求头 = zh-CN,zh;q=0.9              （与真 Chrome 完全一致）
#   navigator.languages = ["zh-CN","zh"] （与真 Chrome 完全一致）

_WARMUP_HTML = "<!doctype html><meta charset='utf-8'><title>.</title>"

_READ_NATIVE = r"""
async () => {
  try {
    if (!navigator.userAgentData) return null;
    const hi = await navigator.userAgentData.getHighEntropyValues(
        ['platform','platformVersion','architecture','bitness','model',
         'uaFullVersion','fullVersionList','wow64']);
    return {ua: navigator.userAgent, hi: hi};
  } catch (e) { return null; }
}
"""


def new_cache():
    """建一个上下文级别的缓存。

    一次进程里每个浏览器上下文一个。它同时承担三件事：
      * 缓存「浏览器原生身份」，避免每开一个页都重读（重读要开临时页）
      * 持有 CDP session 的引用，防止被 GC 掉导致覆写失效
      * 一个重入标记，防止「读原生身份要开临时页 → 临时页又触发钩子 →
        又去读原生身份」这种自我递归
    """
    return {"native": None, "sessions": [], "reading": False, "done": []}


def _native_metadata(context, cache, log=None):
    """用一个临时本地页面读出浏览器**原生**的高熵身份。

    必须在安全上下文里读（about:blank 上 navigator.userAgentData 是 null），
    所以写一个临时 html 用 file:// 打开。读完立刻关掉临时页。

    注意：这个函数会 new_page，所以调用方必须保证不会因此递归回自己 ——
    靠 cache["reading"] 标记来挡。
    """
    if cache is not None and cache.get("reading"):
        return None
    tmp = None
    page = None
    if cache is not None:
        cache["reading"] = True
    try:
        fd, tmp = tempfile.mkstemp(suffix=".html", prefix="thuxk_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_WARMUP_HTML)
        page = context.new_page()
        page.goto(Path(tmp).as_uri(), wait_until="domcontentloaded", timeout=15000)
        data = page.evaluate(_READ_NATIVE)
        if not data or not data.get("ua"):
            return None
        data["hi"] = data.get("hi") or {}
        return data
    except Exception as e:
        if log:
            log("读取浏览器原生身份失败（不影响使用）：%s" % e, "WARN")
        return None
    finally:
        if cache is not None:
            cache["reading"] = False
        try:
            if page is not None:
                page.close()
        except Exception:
            pass
        try:
            if tmp:
                os.unlink(tmp)
        except Exception:
            pass


def build_metadata(native):
    """在浏览器原生身份的基础上，只把品牌列表补成真 Chrome 的样子。

    其它字段（platformVersion / architecture / bitness / model …）一律沿用
    浏览器自己报的值 —— 那些本来就是从操作系统读的，跟是 Chrome 还是
    Chromium 无关，照抄最稳，也不会出现「自造的值和真机不符」。
    """
    hi = (native or {}).get("hi") or {}
    ua = (native or {}).get("ua") or ""
    full = hi.get("uaFullVersion") or ""

    if not full:
        for tok in ua.split():
            if tok.startswith("Chrome/"):
                full = tok.split("/", 1)[1]
                break
    major = full.split(".")[0] if full else ""
    if not major:
        return {}

    return {
        "brands": [
            {"brand": CHROME_BRAND, "version": major},
            {"brand": GREASE_BRAND, "version": GREASE_VERSION},
            {"brand": "Chromium", "version": major},
        ],
        "fullVersionList": [
            {"brand": CHROME_BRAND, "version": full},
            {"brand": GREASE_BRAND, "version": GREASE_FULL},
            {"brand": "Chromium", "version": full},
        ],
        "fullVersion": full,
        "platform": hi.get("platform") or PLATFORM,
        "platformVersion": hi.get("platformVersion") or "",
        "architecture": hi.get("architecture") or ARCHITECTURE,
        "bitness": hi.get("bitness") or BITNESS,
        "model": hi.get("model") or "",
        "mobile": False,
        "wow64": bool(hi.get("wow64") or False),
    }


def apply_to_page(context, page, *, log=None, cache=None):
    """把身份覆写应用到某个页面。可在多个页面上重复调用。"""
    if cache is None:
        cache = new_cache()
    try:
        if page in cache["done"]:
            return True
        native = cache.get("native")
        if native is None:
            native = _native_metadata(context, cache, log=log)
            if not native:
                return False
            cache["native"] = native

        meta = build_metadata(native)
        if not meta:
            return False

        cdp = context.new_cdp_session(page)
        cdp.send("Emulation.setUserAgentOverride", {
            "userAgent": native["ua"],
            "acceptLanguage": ACCEPT_LANGUAGE,
            "platform": "Win32",
            "userAgentMetadata": meta,
        })
        cache["sessions"].append(cdp)      # 持有引用，防止被回收
        cache["done"].append(page)
        if log:
            log("浏览器身份已对齐为 Google Chrome %s（品牌列表一致）"
                % meta["fullVersion"], "DEBUG")
        return True
    except Exception as e:
        if log:
            log("对齐浏览器身份失败（不影响使用）：%s" % e, "WARN")
        return False


def install(context, page, *, log=None, cache=None):
    """给一个上下文装上身份覆写：当前页 + 以后新开的页都自动生效。

    返回 cache，调用方保存它即可（里面有 CDP session 的引用）。
    """
    if cache is None:
        cache = new_cache()
    apply_to_page(context, page, log=log, cache=cache)
    try:
        def _on_page(pg):
            # 预热用的临时页也会触发这个钩子，靠 reading 标记挡掉递归
            if cache.get("reading"):
                return
            apply_to_page(context, pg, log=log, cache=cache)
        context.on("page", _on_page)
    except Exception:
        pass
    return cache