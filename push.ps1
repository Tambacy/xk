<#
    推送助手 —— 有梯子、没梯子都能用
    ==================================

    背景：GitHub 在国内是间歇性可达的，有时通有时不通。
    而且 git 默认**不会**使用 Windows 系统代理，得显式指定。

    这个脚本依次尝试三种方式，任何一种成功就停下：
        1. 直连（大部分时候够用）
        2. 走本地代理（自动探测常见端口，不修改任何 git 配置）
        3. 都不行就提示稍后重试

    用法：
        powershell -ExecutionPolicy Bypass -File push.ps1
        powershell -ExecutionPolicy Bypass -File push.ps1 -Message "改了什么"
#>
param(
    [string]$Message = "",      # 有改动时自动提交的说明
    [string]$Proxy = "",        # 手动指定代理，如 http://127.0.0.1:7897
    [int]$Retries = 3
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

function Say($m, $c = "Gray") { Write-Host $m -ForegroundColor $c }

Say ""
Say "════════════════════════════════════════════════" Cyan
Say " 推送到 GitHub" Cyan
Say "════════════════════════════════════════════════" Cyan

# ---------- 1. 有改动就先提交 ----------
$dirty = git status --porcelain
if ($dirty) {
    Say ""
    Say "有未提交的改动：" Yellow
    $dirty | Select-Object -First 15 | ForEach-Object { Say "  $_" }
    if (-not $Message) {
        $Message = Read-Host "`n请输入提交说明（直接回车则用时间戳）"
        if (-not $Message) { $Message = "更新 $(Get-Date -Format 'yyyy-MM-dd HH:mm')" }
    }
    git add -A
    git commit -q -m $Message
    if ($LASTEXITCODE -ne 0) { Say "提交失败" Red; exit 1 }
    Say "  ✅ 已提交" Green
} else {
    Say "`n 工作区干净，直接推送" Green
}

# ---------- 2. 探测可用代理 ----------
function Find-Proxy {
    if ($Proxy) { return $Proxy }
    foreach ($p in @(7897, 7890, 7891, 10809, 10808, 1080, 2080, 8888)) {
        $c = New-Object System.Net.Sockets.TcpClient
        try {
            $r = $c.BeginConnect("127.0.0.1", $p, $null, $null)
            if ($r.AsyncWaitHandle.WaitOne(300) -and $c.Connected) { return "http://127.0.0.1:$p" }
        } catch { } finally { $c.Close() }
    }
    return ""
}

# ---------- 3. 依次尝试 ----------
function Try-Push($label, $proxyUrl) {
    Say ""
    if ($proxyUrl) { Say "尝试：$label（$proxyUrl）" Cyan } else { Say "尝试：$label" Cyan }
    # 用环境变量而**不是** git config —— 不往任何配置文件里写东西，
    # 免得哪天梯子关了反而推不上去
    $old = $env:HTTPS_PROXY
    if ($proxyUrl) { $env:HTTPS_PROXY = $proxyUrl }
    try {
        for ($i = 1; $i -le $Retries; $i++) {
            if ($Retries -gt 1) { Say "  第 $i/$Retries 次…" }
            $out = git push 2>&1
            if ($LASTEXITCODE -eq 0) {
                Say "  ✅ 推送成功" Green
                git log --oneline -1 | ForEach-Object { Say "     $_" }
                return $true
            }
            $err = ($out | Select-Object -Last 1)
            Say "  ✗ $err" DarkGray
            if ($i -lt $Retries) { Start-Sleep -Seconds (2 * $i) }
        }
    } finally {
        $env:HTTPS_PROXY = $old
    }
    return $false
}

$ok = Try-Push "直连" ""

if (-not $ok) {
    $p = Find-Proxy
    if ($p) {
        $ok = Try-Push "本地代理" $p
    } else {
        Say ""
        Say "  没探测到本地代理在运行" Yellow
    }
}

# ---------- 4. 结果 ----------
Say ""
Say "════════════════════════════════════════════════" Cyan
if ($ok) {
    Say " 完成" Green
    Say " 仓库：https://github.com/Tambacy/xk" Green
    Say " 发布：https://github.com/Tambacy/xk/releases" Green
    exit 0
} else {
    Say " 推送失败" Red
    Say ""
    Say " GitHub 在国内是间歇性可达的，最可能的原因就是这会儿不通。" Yellow
    Say " 建议：" Yellow
    Say "   1. 等几分钟重跑一次（大部分时候这样就够了）"
    Say "   2. 挂上梯子后再跑一次，脚本会自动识别并走代理"
    Say "   3. 手动指定代理："
    Say "        .\push.ps1 -Proxy http://127.0.0.1:7897"
    Say ""
    Say " 你的改动已经提交到本地了，不会丢。" Green
    exit 1
}
