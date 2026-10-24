; Windows installer for Sims 4 Mod Test (Inno Setup 6). Built by packaging/build.py, which passes
; the version: ISCC /DAppVersion=1.0.0 packaging\Sims4ModTest.iss

#define AppName "Sims 4 Mod Test"
#define AppExe "Sims 4 Mod Test.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{5E0B6C2D-3A71-4F8E-9C24-7D1A0B9E6F43}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=stixez
AppPublisherURL=https://github.com/stixez/Sims4ModTest
AppSupportURL=https://github.com/stixez/Sims4ModTest/issues
AppUpdatesURL=https://github.com/stixez/Sims4ModTest/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Sims-4-Mod-Test-{#AppVersion}-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSizePercent=100
WizardImageFile=..\assets\wizard-100.bmp,..\assets\wizard-150.bmp,..\assets\wizard-200.bmp
WizardSmallImageFile=..\assets\wizard-small-100.bmp,..\assets\wizard-small-150.bmp,..\assets\wizard-small-200.bmp
WizardImageStretch=no
WizardImageBackColor=$F2F5F6
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Install Sims 4 Mod Test
WelcomeLabel2=Try Sims 4 mods on their own, find the mod that breaks your game, and put everything back with one click.%n%nYour own mods are only ever set aside, never changed.
FinishedHeadingLabel=Sims 4 Mod Test is installed
FinishedLabelNoIcons=Sims 4 Mod Test is installed on your computer.
FinishedLabel=Sims 4 Mod Test is installed on your computer. You can open it from the Start menu.

[Tasks]
Name: "desktopicon"; Description: "Add a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Sims 4 Mod Test\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; files of an older version that the new one no longer has
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "stixez.Sims4ModTest"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; AppUserModelID: "stixez.Sims4ModTest"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open Sims 4 Mod Test now"; Flags: nowait postinstall skipifsilent

[Code]
// A running test has the user's own Mods set aside; removing the app then would leave them there
// with nothing on screen saying how to get them back.
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if FileExists(ExpandConstant('{localappdata}\Sims 4 Mod Test\state.json')) then
  begin
    MsgBox('A test is still running, so your own mods are set aside. Open Sims 4 Mod Test and press ' +
           '"Restore my mods" first, then uninstall.', mbInformation, MB_OK);
    Result := False;
  end;
end;
