# -*- coding: utf-8 -*-
"""
无头浏览器的"补妆"脚本
======================

**先说清楚：这是下策。** 最好的办法是压根不用无头 —— 有头模式下这些破绽
一个都不存在，因为那本来就是一台正常的 Chrome，用真显卡在渲染。

但如果因为某些原因必须无头跑，这个脚本能把最常见的几个识别点抹掉：

    1. navigator.plugins / mimeTypes 为空      → 真 Chrome 有 5 个插件
    2. window.chrome 缺失                       → 真 Chrome 一定有
    3. WebGL 报 SwiftShader（软件渲染）          → 真机器是显卡
    4. navigator.pdfViewerEnabled 为 false      → 真 Chrome 是 true
    5. 内外窗口尺寸完全相等                       → 真窗口有边框和标题栏

注意：这是"伪装"，不是"变成真人"。JS 层面的检测点远不止这几个，
真要做反检测还得靠有头模式。所以这个脚本只在 `headless=True` 时才注入。
"""

# 真实的 Chrome 151 在 Windows 上报告的内容
PLUGINS = [
    {"name": "PDF Viewer", "filename": "internal-pdf-viewer",
     "desc": "Portable Document Format"},
    {"name": "Chrome PDF Viewer", "filename": "internal-pdf-viewer",
     "desc": "Portable Document Format"},
    {"name": "Chromium PDF Viewer", "filename": "internal-pdf-viewer",
     "desc": "Portable Document Format"},
    {"name": "Microsoft Edge PDF Viewer", "filename": "internal-pdf-viewer",
     "desc": "Portable Document Format"},
    {"name": "WebKit built-in PDF", "filename": "internal-pdf-viewer",
     "desc": "Portable Document Format"},
]
MIME_TYPES = [
    {"type": "application/pdf", "suffixes": "pdf", "desc": "Portable Document Format"},
    {"type": "text/pdf", "suffixes": "pdf", "desc": "Portable Document Format"},
]

# 一台常见 Windows 机器会报的显卡信息（用 NVIDIA 集显/独显的通用串，不指向具体某人）
WEBGL_VENDOR = "Google Inc. (NVIDIA)"
WEBGL_RENDERER = ("ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)")

INIT_SCRIPT = r"""
(() => {
  const DEFINE = (obj, prop, value) => {
    try {
      Object.defineProperty(obj, prop, { get: () => value, configurable: true });
    } catch (e) { /* 某些属性不可重定义，忽略 */ }
  };

  // ---------- 1. 插件 ----------
  const pluginData = %PLUGINS%;
  const mimeData   = %MIMES%;
  try {
    const mkPlugin = (p, i) => {
      const o = Object.create(Plugin.prototype);
      DEFINE(o, 'name', p.name);
      DEFINE(o, 'filename', p.filename);
      DEFINE(o, 'description', p.desc);
      DEFINE(o, 'length', mimeData.length);
      return o;
    };
    const mkMime = (m) => {
      const o = Object.create(MimeType.prototype);
      DEFINE(o, 'type', m.type);
      DEFINE(o, 'suffixes', m.suffixes);
      DEFINE(o, 'description', m.desc);
      DEFINE(o, 'enabledPlugin', null);
      return o;
    };
    const plugins = pluginData.map(mkPlugin);
    const mimes   = mimeData.map(mkMime);
    plugins.forEach(p => { p.item = i => plugins[i]; p.namedItem = n => plugins.find(x => x.name === n) || null; });
    mimes.forEach(m => { m.item = i => mimes[i]; m.namedItem = n => mimes.find(x => x.type === n) || null; });

    const pa = Object.create(PluginArray.prototype);
    plugins.forEach((p, i) => { pa[i] = p; });
    DEFINE(pa, 'length', plugins.length);
    pa.item = i => plugins[i] || null;
    pa.namedItem = n => plugins.find(x => x.name === n) || null;
    pa.refresh = () => {};
    DEFINE(navigator, 'plugins', pa);

    const ma = Object.create(MimeTypeArray.prototype);
    mimes.forEach((m, i) => { ma[i] = m; });
    DEFINE(ma, 'length', mimes.length);
    ma.item = i => mimes[i] || null;
    ma.namedItem = n => mimes.find(x => x.type === n) || null;
    DEFINE(navigator, 'mimeTypes', ma);
  } catch (e) {}

  // ---------- 2. window.chrome ----------
  try {
    if (!window.chrome) {
      window.chrome = {};
    }
    if (!window.chrome.runtime) {
      window.chrome.runtime = {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install',
                             SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update',
                                   PERIODIC: 'periodic' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64',
                        X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac',
                      OPENBSD: 'openbsd', WIN: 'win' },
        RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled',
                                    UPDATE_AVAILABLE: 'update_available' },
      };
    }
    if (!window.chrome.app) {
      window.chrome.app = {
        isInstalled: false,
        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
        getDetails: () => null,
        getIsInstalled: () => false,
      };
    }
  } catch (e) {}

  // ---------- 3. WebGL 渲染器 ----------
  try {
    const patch = (proto) => {
      if (!proto) return;
      const orig = proto.getParameter;
      proto.getParameter = function (p) {
        // 37445 = UNMASKED_VENDOR_WEBGL, 37446 = UNMASKED_RENDERER_WEBGL
        if (p === 37445) return %WGL_VENDOR%;
        if (p === 37446) return %WGL_RENDERER%;
        // 7936 = VENDOR, 7937 = RENDERER
        if (p === 7936) return 'WebKit';
        if (p === 7937) return 'WebKit WebGL';
        return orig.apply(this, arguments);
      };
    };
    patch(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
    patch(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);
  } catch (e) {}

  // ---------- 4. PDF 查看器 ----------
  DEFINE(navigator, 'pdfViewerEnabled', true);

  // ---------- 5. 窗口尺寸：真窗口比内容区大一圈 ----------
  // 用 getter 实时算，因为 init script 执行时窗口还没定尺寸
  try {
    Object.defineProperty(window, 'outerWidth', {
      get() { return (window.innerWidth || 0) + 16; }, configurable: true,
    });
    Object.defineProperty(window, 'outerHeight', {
      get() { return (window.innerHeight || 0) + 88; }, configurable: true,
    });
  } catch (e) {}

  // ---------- 6. 顺手把 webdriver 也抹掉 ----------
  DEFINE(navigator, 'webdriver', undefined);
})();
"""


def build_init_script() -> str:
    """生成可以直接喂给 add_init_script 的脚本。"""
    import json
    return (INIT_SCRIPT
            .replace("%PLUGINS%", json.dumps(PLUGINS, ensure_ascii=False))
            .replace("%MIMES%", json.dumps(MIME_TYPES, ensure_ascii=False))
            .replace("%WGL_VENDOR%", json.dumps(WEBGL_VENDOR))
            .replace("%WGL_RENDERER%", json.dumps(WEBGL_RENDERER)))


# 不管有没有头，这个都该加（虽然真 Chrome 本来就是 undefined）
MINIMAL_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});"
)
