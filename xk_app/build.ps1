<#
    选课助手 —— 一键构建
    =========================
    用法（在项目目录下）：
        powershell -ExecutionPolicy Bypass -File build.ps1

    做三件事：
        1. 生成图标
        2. PyInstaller 打包成 exe（onedir）
        3. Inno Setup 打成安装包

    产物：
        dist\XkHelper\                      可直接运行的目录版
        installer\XkHelper-Setup-x.y.z.exe  安装包
#>
param(
    [switch]$SkipInstaller,      # 只出 exe，不出安装包
    [switch]$Console             # 出带控制台的调试版
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

function Step($n, $t) { Write-Host "`n=== [$n] $t ===" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "  [X]  $m" -ForegroundColor Red; exit 1 }

# ---- 找 Python（必须是装了 PySide6 / playwright 的那个 3.13）----
$Py = "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python313\python.exe"
if (-not (Test-Path $Py)) {
    $cand = Get-Command python -ErrorAction SilentlyContinue
    if ($cand) { $Py = $cand.Source } else { Die "找不到 Python" }
}
& $Py -c "import PySide6, playwright, PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { Die "当前 Python 缺少 PySide6 / playwright / PyInstaller：$Py" }
Ok "Python: $Py"

# ---- 1. 图标 ----
Step 1 "生成图标"
& $Py make_icon.py
if ($LASTEXITCODE -ne 0) { Die "图标生成失败" }
Ok "assets\app.ico"

# ---- 2. 语法自检 ----
Step 2 "语法检查"
& $Py -m py_compile main.py
if ($LASTEXITCODE -ne 0) { Die "语法检查未通过" }
Ok "main.py 及依赖编译通过"

# ---- 3. PyInstaller ----
Step 3 "PyInstaller 打包"
if ($Console) { $env:XK_CONSOLE = "1" } else { $env:XK_CONSOLE = "0" }

# ⚠ 上一次构建会在 dist 里留下一个指向 ms-playwright 的**目录联接**（见第 4 步）。
# Windows PowerShell 5.1 的 Remove-Item -Recurse 会顺着联接一路删进**目标目录**，
# 也就是把你本机装好的 Playwright 浏览器删掉（得重新下 ~400MB 才能再构建）。
# 所以先用 rmdir（只摘链接本身，绝不碰目标）把联接去掉，再删 dist。
$linkParent = "dist\XkHelper\_internal\browsers"
if (Test-Path $linkParent) {
    Get-ChildItem $linkParent -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
        ForEach-Object {
            Warn "先摘掉目录联接（避免连带删掉真实浏览器）：$($_.FullName)"
            cmd /c "rmdir `"$($_.FullName)`"" 2>$null | Out-Null
        }
}
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
& $Py -m PyInstaller xk.spec --noconfirm --clean --log-level WARN
if ($LASTEXITCODE -ne 0) { Die "PyInstaller 失败" }
$dist = "dist\XkHelper"
if (-not (Test-Path "$dist\XkHelper.exe")) { Die "没生成 exe" }
$exeMB = [math]::Round((Get-ChildItem $dist -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Ok "$dist  ($exeMB MB)"

# ---- 4. 放浏览器 ----
Step 4 "放入随包 Chromium"
# Playwright 的浏览器在用户目录下，构建时用目录联接放进去，
# 这样本地测试快；真正的安装包由 Inno Setup 直接引用源目录，不走这里。
$chromeSrc = Get-ChildItem "$env:LOCALAPPDATA\ms-playwright" -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue |
             Sort-Object Name -Descending | Select-Object -First 1
if (-not $chromeSrc) { Warn "没找到 ms-playwright\chromium-*，跳过（本地运行会回退到默认查找）" }
else {
    $bdst = "$dist\_internal\browsers"
    New-Item -ItemType Directory -Force -Path $bdst | Out-Null
    $link = Join-Path $bdst $chromeSrc.Name
    if (Test-Path $link) { cmd /c rmdir "$link" 2>$null | Out-Null }
    cmd /c mklink /J "$link" "$($chromeSrc.FullName)" | Out-Null
    Ok "$($chromeSrc.Name) -> _internal\browsers"
}

# ---- 5. 自检 ----
Step 5 "打包后自检"
$env:XK_HOME = Join-Path $Root "data\build-selftest"
Remove-Item -Recurse -Force $env:XK_HOME -ErrorAction SilentlyContinue

# 注意：XkHelper.exe 是 GUI 子系统程序（windowed）。直接 `& exe args`
# 时 PowerShell **不会等**这个进程结束，$LASTEXITCODE 会保留上一条命令的值 ——
# 实测自检明明失败了，$LASTEXITCODE 仍是 0，于是「自检不过就中止」这道
# 安全网形同虚设，坏包照样会被发出去。
#
# 把它接进管道（| Out-String）就会强制 PowerShell 等它跑完、并正确设置
# $LASTEXITCODE。不要改成 Start-Process：在某些受限环境下它会被拒绝访问。
$exePath = Join-Path $Root "$dist\XkHelper.exe"
if (-not (Test-Path $exePath)) { Die "自检找不到 exe：$exePath" }
$selftestOut  = & $exePath --selftest 2>&1 | Out-String
$selftestCode = $LASTEXITCODE
$selftestLog  = Join-Path $Root "data\selftest-output.txt"
$selftestOut | Set-Content -Path $selftestLog -Encoding UTF8
$selftestOut.Trim() -split "`r?`n" | Select-Object -Last 20 |
    ForEach-Object { Write-Host "    $_" }
if ($selftestCode -ne 0) {
    Warn "完整自检输出：$selftestLog"
    Die "自检未通过（退出码 $selftestCode），先别发安装包"
}
Ok "自检通过"

# ---- 6. Inno Setup ----
if ($SkipInstaller) { Write-Host "`n已跳过安装包生成。" -ForegroundColor Yellow; exit 0 }
Step 6 "生成安装包"
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Die "没装 Inno Setup 6。装一个： winget install JRSoftware.InnoSetup" }

# Inno 脚本里写的 Chromium 目录名会随 Playwright 升级而变化，写死的话打完包
# 才发现浏览器没进去（或者版本不对）。这里把实际目录名传进去。
$chromeDirName = Get-ChildItem "$env:LOCALAPPDATA\ms-playwright" -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending | Select-Object -First 1 |
                 Select-Object -ExpandProperty Name
if (-not $chromeDirName) { Die "没找到 ms-playwright\chromium-*，安装包会缺少浏览器" }
Ok "随包 Chromium 目录：$chromeDirName"

& $iscc "/DChromiumDir=$chromeDirName" installer.iss | Select-String -Pattern "Successful|Error" | ForEach-Object { $_.Line }
if ($LASTEXITCODE -ne 0) { Die "Inno Setup 编译失败" }
$setup = Get-ChildItem installer\*.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$setupMB = [math]::Round($setup.Length / 1MB, 1)
Ok "$($setup.FullName)  ($setupMB MB)"

Write-Host "`n============================================" -ForegroundColor Green
Write-Host " 构建完成" -ForegroundColor Green
Write-Host "  目录版：$dist" -ForegroundColor Green
Write-Host "  安装包：$($setup.FullName)  ($setupMB MB)" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

# 显式返回 0：脚本里跑过不少原生命令，$LASTEXITCODE 会残留最后一条的值，
# 用 `powershell -File build.ps1` 调用时会把「成功」报成非零退出码，
# 自动化里就会被当成构建失败。
exit 0
