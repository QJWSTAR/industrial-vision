; CSAM Repair Software — Inno Setup Installer Script
; v1.0.0 — 冷喷涂缺陷修复软件 Windows 安装程序
;
; 用法:
;   1. 安装 Inno Setup (https://jrsoftware.org/isinfo.php)
;   2. 运行 build_windows.bat 生成 dist\CSAM_Repair.exe
;   3. 打开 Inno Setup Compiler，编译本脚本
;   4. 输出: installer\Output\CSAM_Repair_Setup.exe
;
; 支持: 安装 / 升级 / 卸载 / 开始菜单快捷方式 / MATLAB 检测

#define MyAppName "CSAM Repair"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "CSAM Industrial Vision"
#define MyAppURL "https://example.com/csam"
#define MyAppExeName "CSAM_Repair.exe"
#define MyAppDescription "冷喷涂缺陷修复软件"

[Setup]
; 基础信息
AppId={{B8F4A3D2-7E1C-4A5B-9D6F-1C8E3A7B2D5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppDescription}

; 许可协议
LicenseFile=..\EULA.txt

; 安装目录
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; 输出
OutputDir=Output
OutputBaseFilename=CSAM_Repair_Setup_v{#MyAppVersion}
SetupIconFile=..\p1.ico

; 压缩
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; 权限（需要管理员权限写入 Program Files）
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

; 卸载时自动关闭运行中的程序
CloseApplications=yes
RestartApplications=no

; 禁用"选择安装目录"页面的修改（可选，取消注释以启用）
; DisableDirPage=auto

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; 自定义中文提示（如果使用中文语言包）
chinesesimplified.BeveledLabel={#MyAppName} v{#MyAppVersion}

[Types]
Name: "full"; Description: "完整安装"
Name: "compact"; Description: "精简安装"
Name: "custom"; Description: "自定义安装"; Flags: iscustom

[Components]
Name: "main"; Description: "主程序（必需）"; Types: full compact custom; Flags: fixed
Name: "desktop"; Description: "桌面快捷方式"; Types: full
Name: "config"; Description: "配置文件（公钥）"; Types: full compact custom; Flags: fixed

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Components: desktop

[Files]
; 主程序
Source: "..\dist\CSAM_Repair.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: main

; 配置文件（公钥 — 安全关键，必须打包）
Source: "..\config\public_key.pem"; DestDir: "{app}\config"; Flags: ignoreversion; Components: config

; 配置文件（开发模式默认配置）
Source: "..\config\app_config.json"; DestDir: "{app}\config"; Flags: ignoreversion; Components: config

; MATLAB 算法脚本（可选，用于 MATLAB Bridge 模式）
Source: "..\matlab_bridge_server.m"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "..\path_planning\*"; DestDir: "{app}\path_planning"; Flags: ignoreversion recursesubdirs; Components: main
Source: "..\profile_prediction\*"; DestDir: "{app}\profile_prediction"; Flags: ignoreversion recursesubdirs; Components: main

; 分发版配置文件（空目录，运行时由程序自动填充）
Source: "..\dist\config\public_key.pem"; DestDir: "{app}\config"; Flags: ignoreversion; Components: config

; 法律文件
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "..\EULA.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "..\THIRD_PARTY_NOTICES"; DestDir: "{app}"; Flags: ignoreversion; Components: main

[Icons]
; 开始菜单
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppDescription}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

; 桌面快捷方式（可选）
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "{#MyAppDescription}"

[Run]
; 安装完成后询问是否运行
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 清理运行时生成的文件（日志、缓存等）
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\cache"

[Code]
// ============================================================
// MATLAB 检测
// ============================================================
var
  MatlabDetectedPage: TOutputMsgWizardPage;

function IsMatlabInstalled: Boolean;
var
  Version: String;
begin
  Result := False;
  // 检查 MATLAB R2023b 及以上版本
  if RegQueryStringValue(HKLM, 'SOFTWARE\MathWorks\MATLAB\9.15', 'MATLABROOT', Version) then
    Result := True
  else if RegQueryStringValue(HKLM, 'SOFTWARE\MathWorks\MATLAB\9.14', 'MATLABROOT', Version) then
    Result := True
  else if RegQueryStringValue(HKLM, 'SOFTWARE\MathWorks\MATLAB\9.13', 'MATLABROOT', Version) then
    Result := True;
end;

function GetMatlabVersion: String;
var
  Version: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'SOFTWARE\MathWorks\MATLAB\9.15', 'MATLABROOT', Version) then
    Result := 'R2025b'
  else if RegQueryStringValue(HKLM, 'SOFTWARE\MathWorks\MATLAB\9.14', 'MATLABROOT', Version) then
    Result := 'R2025a'
  else if RegQueryStringValue(HKLM, 'SOFTWARE\MathWorks\MATLAB\9.13', 'MATLABROOT', Version) then
    Result := 'R2024b';
end;

// 显示 MATLAB 检测结果
procedure InitializeWizard;
var
  MatlabMsg: String;
begin
  MatlabDetectedPage := CreateOutputMsgPage(wpWelcome,
    'MATLAB 环境检测', '正在检查 MATLAB 运行环境...',
    '');

  if IsMatlabInstalled then
    MatlabMsg := '已检测到 MATLAB ' + GetMatlabVersion + '。' + #13#10 +
                 'MATLAB Bridge 加速模式可用（可选）。' + #13#10 +
                 '软件默认使用本地 Python 引擎，无需 MATLAB 也可运行。'
  else
    MatlabMsg := '未检测到 MATLAB 安装。' + #13#10 +
                 '软件将使用本地 Python 引擎运行，所有功能正常。' + #13#10 +
                 '如需 MATLAB Bridge 加速模式，请安装 MATLAB R2024b 或更高版本。';

  MatlabDetectedPage.Text := MatlabMsg;
end;

// 检查已安装版本（升级场景）
function GetPreviousVersion: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}_is1',
    'DisplayVersion', Result) then
  begin
    // 已找到旧版本
  end;
end;

// 安装前检查
function InitializeSetup: Boolean;
var
  PrevVersion: String;
begin
  Result := True;
  PrevVersion := GetPreviousVersion;
  if PrevVersion <> '' then
  begin
    if MsgBox('检测到已安装的 {#MyAppName} v' + PrevVersion + '。' + #13#10#13#10 +
              '是否继续安装（将覆盖旧版本）？',
              mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
    end;
  end;
end;