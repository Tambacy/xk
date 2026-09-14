; ============================================================================
;  学校选课助手 —— Inno Setup 安装包脚本
; ============================================================================
;  自包含：Python 运行时 + PySide6 + Playwright 驱动 + 整个 Chromium 都在包里，
;  装完即可用，不需要联网下载任何东西。
;
;  用法：
;      "C:\Users\<你>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
;  或直接跑 build.ps1
; ============================================================================

#define AppName        "学校选课助手"
#define AppNameEn      "THU XkHelper"
#define AppVersion     "0.1.0"
#define AppPublisher   "个人自用"
#define AppExeName     "XkHelper.exe"

; 源目录：PyInstaller 的 onedir 产物
#define DistDir        "dist\XkHelper"

; 随包 Chromium（直接引用本机 ms-playwright 目录，不打进 PyInstaller，构建快得多）
#define ChromiumSrc    GetEnv("LOCALAPPDATA") + "\ms-playwright\chromium-1234"

[Setup]
AppId={{8F3C1A62-7B4E-4D19-9C2A-5E7D6B1F0A34}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppNameEn}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=XkHelper-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
; 427MB 的浏览器 + 150MB 的运行时，压缩很慢，给足时间
LZMANumBlockThreads=4

[Languages]
Name: "chinese"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
; ---- 程序本体 ----
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ---- 使用说明（放到安装目录顶层，方便直接双击打开）----
Source: "docs\使用说明.html"; DestDir: "{app}"; Flags: ignoreversion

; ---- 随包 Chromium（装到 _internal\browsers，与 runtime.py 的约定一致）----
Source: "{#ChromiumSrc}\*"; DestDir: "{app}\_internal\browsers\chromium-1234"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.html"
Name: "{group}\日志目录"; Filename: "{localappdata}\XkHelper\logs"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即运行 {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时不要把用户数据（配置/凭据/日志）删掉，免得误删。
; 需要彻底清理的话，单独删 %LOCALAPPDATA%\XkHelper 即可。
Type: filesandordirs; Name: "{app}\_internal\browsers"
Type: files; Name: "{app}\install-info.txt"

[Code]
// 安装前检查磁盘空间：整个包解开大约 600MB
function InitializeSetup(): Boolean;
var
  FreeBytes, TotalBytes: Int64;
  FreeMB: Int64;
begin
  Result := True;
  if GetSpaceOnDisk64(ExpandConstant('{sd}\'), FreeBytes, TotalBytes) then
  begin
    FreeMB := FreeBytes div 1048576;
    if FreeMB < 900 then
    begin
      if MsgBox('安装需要约 600MB 空间，当前可用 ' + IntToStr(FreeMB) +
                'MB。仍要继续吗？', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 记录安装位置，方便排查问题时定位
    SaveStringToFile(ExpandConstant('{app}\install-info.txt'),
      '安装时间: ' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':') + #13#10 +
      '安装目录: ' + ExpandConstant('{app}') + #13#10 +
      '版本: {#AppVersion}' + #13#10, False);
  end;
end;
