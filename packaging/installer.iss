; Inno Setup script → dist\PDFSoul-By-Billy-Setup-<version>.exe
; Build: iscc /DAppVersion=0.1.0 packaging\installer.iss   (build_windows.ps1 does this)

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "PDFSoul By Billy"
#define AppExe "PDFSoul.exe"
#define ProgId "PDFSoul.Document"

[Setup]
AppId={{6B1E2A54-3C2F-4E0B-9C2A-5D0F1B7A9E31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Billy Brightson
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=PDFSoul-By-Billy-Setup-{#AppVersion}
SetupIconFile=pdfsoul.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "openwith"; Description: "Add PDFSoul to the PDF ""Open with"" list"; GroupDescription: "Integration:"
Name: "contextmenu"; Description: "Add ""Compress with PDFSoul"" and ""Split with PDFSoul"" to the right-click menu"; GroupDescription: "Integration:"
Name: "addtopath"; Description: "Add the ""pdfsoul"" command to PATH"; GroupDescription: "Integration:"; Flags: unchecked

[Files]
Source: "..\dist\PDFSoul\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; ProgID used by "Open with" and the context menu entries.
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF document"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey; Tasks: openwith

; Right-click entries on any PDF (open the app with that tool selected).
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFSoul.Compress"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Compress with PDFSoul"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFSoul.Compress"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFSoul.Compress\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tool compress ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFSoul.Split"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Split with PDFSoul"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFSoul.Split"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFSoul.Split\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --tool split ""%1"""; Tasks: contextmenu

; Optional: put the install folder on the user's PATH so `pdfsoul` (pdfsoul.com) works.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}')); Tasks: addtopath

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
