# 学校选课助手

自动盯课余量、按预定时间抢课。全程用**真实 Chromium 浏览器**操作 ——
登录、点页签、勾选课程、点提交都是像人一样的真实鼠标键盘事件，
不发送任何脚本化的后台请求。

## 下载

到 [**Releases**](https://github.com/Tambacy/xk/releases) 页面下载：

| 文件 | 大小 | 说明 |
|---|---|---|
| `XkHelper-Setup-0.1.0.exe` | 334 MB | **安装包**，推荐。自包含，装完即用 |
| `XkHelper-v0.1.0-source.zip` | 607 KB | 源码，想自己改或自己构建就下这个 |

安装包体积大是因为**内置了一整个 Chromium**（解压后 426 MB）——
这样程序才能用真实浏览器操作，而不是发脚本化的 HTTP 请求。

![登录](xk_app/docs/screenshots/1-login.png)

<details>
<summary>更多界面截图</summary>

**选择运行模式** —— 三张卡片对号入座：

![模式](xk_app/docs/screenshots/2-mode.png)

**预定课程** —— 左侧录入，右侧自动校验并出卡片（已定位 / 需补充 / 时间冲突）：

![课程](xk_app/docs/screenshots/3-courses.png)

**确认启动** —— 红字提醒不要关程序：

![确认](xk_app/docs/screenshots/4-confirm.png)

**运行监控** —— 状态、统计、实时日志：

![监控](xk_app/docs/screenshots/5-monitor.png)

</details>

---

## 它能做什么

按你设定的节奏反复检查目标课程有没有课余量，一旦发现就（必要时先退掉占位的课）
立刻提交选课。它**不**替你决定选什么课，也**不**能提高中签率 ——
它解决的是"别人退课的那一瞬间我不在电脑前"这个问题。

| | 能做 | 不能做 |
|---|---|---|
| | 按时间点自动开始选课<br>长期监听课余量，发现就抢<br>抢之前自动退掉冲突/让位的课<br>抢不到自动把退掉的课选回来<br>会话过期自动重新登录 | 在报名/抽签阶段插队<br>绕过系统的任何限制<br>在程序关着的时候帮你盯着 |

---

## 三种运行模式

| 模式 | 适用场景 | 行为 |
|---|---|---|
| **一** | 选课还没开始（投了要抽签） | 按学校通知的时间提前盯「当前选课阶段」，一变成先到先得就自动选课 |
| **二** | 马上开始，且已有课要让位 | 到点先退冲突课再抢；抢不到自动把退掉的课选回来 |
| **三** | 选课进行中，蹲别人退课 | 长期监听，可设平均间隔（最长 1 小时）；发现余量立刻抢 |

拟人化程度按模式区分：模式一/三慢节奏（间隔随机长尾、偶尔走神、夜间静默），
模式二等待期间拟人化、**动手那一瞬间全速**。

---

## 安装使用

### 直接运行

```
xk_app\dist\XkHelper\XkHelper.exe
```

### 构建安装包

```powershell
cd xk_app
powershell -ExecutionPolicy Bypass -File build.ps1
# 产物：installer\XkHelper-Setup-0.1.0.exe（约 330 MB，自包含）
```

依赖：Python 3.13 + PySide6 + playwright + PyInstaller + Inno Setup 6。
`build.ps1` 会自动完成打包和**打包后自检**，自检不过就中止，不会把坏包发出去。

### 首次登录

使用学校统一身份认证账号。**登录可能要求二次验证**（短信/微信），
此时会弹出浏览器窗口，请在那里完成 —— 一次之后本机就被记住了。

登录通常 10~40 秒，界面会实时显示当前阶段和已用时间。

---

## 项目结构

```
xk_app/
  app/
    browser.py          浏览器会话 + 教务系统页面操作
    courses.py          课程定位 + 周次感知的时间冲突检测
    humanize.py         拟人化引擎（节奏档位 / 鼠标轨迹 / 逐字输入）
    scheduler.py        三种运行模式的调度器
    secretstore.py      DPAPI 凭据加密 + 日志脱敏
    logging_setup.py    双通道轮转日志 + 诊断包导出
    stealth.py          无头模式的指纹补妆
    runtime.py          打包后的路径处理
    config.py           配置持久化（原子写 + BOM 容错）
    gui/
      main_window.py    主窗口
      pages.py          登录 / 模式 / 课程 / 确认 / 监控 五个页面
      core.py           界面与浏览器之间的桥（工作线程）
      widgets.py        通用组件
      theme.py          配色与样式表
  docs/使用说明.html     随安装包发布的使用说明
  main.py              入口（含 --selftest 自检）
  xk.spec           PyInstaller 配置
  installer.iss        Inno Setup 配置
  build.ps1            一键构建
  test_*.py            测试
```

---

## 设计要点

### 为什么用浏览器而不是 HTTP 请求

裸 HTTP 请求会暴露 Python 库的 TLS 指纹、缺失的浏览器请求头、
`isTrusted=false` 的合成事件 —— 这些都是明显的脚本特征。用真实浏览器则这些全都不是问题。

代价是安装包大了（要带一整个 Chromium，约 330 MB）。

### 拟人化

- 轮询间隔随机浮动，带长尾停顿，且**取值区间连续** ——
  用乘法而非加法制造长尾，否则直方图会留下永远取不到的空档，
  长期统计一眼就能看出是程序
- 相邻两次间隔不雷同；鼠标走 smoothstep 轨迹带弧度；输入逐字敲并有偶发卡顿
- 夜间 01:00~06:00 零请求
- 会话过期自动重登；抢课中途掉线先重登再继续，不半途而废

### 隐私

- 账号密码用 Windows DPAPI 加密，绑定当前用户 + 当前电脑，**明文不落盘**
- 日志、诊断包里的密码、学号、Cookie 全部自动打码成 `***`
- **安装包不含任何账号数据**；凭据存在 `%LOCALAPPDATA%\XkHelper\`，不随安装分发
- 登录页有「清除本机已保存的账号密码」按钮

---

## 踩过的坑

留在这里，免得以后重蹈覆辙。

1. **token 一次性且 HTML 里跨行** —— `name="token"` 和 `value` 之间会换行，
   按单行正则会全部匹配失败，得到「令牌失效」
2. **页面是 GBK** —— 中文参数必须按 GBK 百分号编码；浏览器表单提交天然正确
3. **连续快速提交选课会被判「请输入正确的验证码」** —— 系统防刷，间隔 ≥2.5 秒不触发
4. **每学期只能选一门体育课** —— 抢新的之前必须先退掉旧的
5. **「课表查询」页面显示为空** —— 权威的已选课程列表是 `m=yxSearchTab`
6. **各类课程页列数不同**（必修 10 列 / 任选 11 列 / 体育 8 列）—— 必须按表头名映射列
7. **URL 筛选只有体育课认** —— 其他类别必须走页面真实搜索；
   任选课不搜索永远是「没有记录」
8. **登录过期是 HTTP 200 + 355 字节小页面** —— 不是 401，不能靠状态码判断
9. **PyInstaller windowed 模式下 `sys.stdout` 是 None** ——
   Playwright 起 node 子进程会一直卡住不返回
10. **GBK 控制台 + emoji** → `UnicodeEncodeError` → windowed 模式静默崩溃，
    日志断在半截，看起来像"浏览器启动失败"，其实浏览器早起来了
11. **系统 Edge 会触发二次认证，Playwright 自带 Chromium 不会** ——
    所以安装包必须自带浏览器，不能借用系统的

---

## 测试

```powershell
cd xk_app
& $PY test_security_logging.py    # 22 项：DPAPI 加解密、日志脱敏、诊断包
& $PY test_scheduler.py           # 选课阶段判断、让位逻辑、真实环境干跑
& $PY test_e2e.py                 # 端到端：登录→校验→监听→停止
& $PY test_gui_smoke.py           # 界面渲染回归
```

打包后自检（不需要图形界面、不需要登录）：

```powershell
.\dist\XkHelper\XkHelper.exe --selftest
```

---

## 免责

仅供本人选课使用。请遵守学校相关规定，合理设置监听间隔，不要给服务器造成压力。
