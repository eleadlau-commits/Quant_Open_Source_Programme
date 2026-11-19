; Titanium Windows installer (Inno Setup 6).
; Built by .github/workflows/desktop-build.yml:
;   python packaging/build_exe.py --onedir      (bundled-Python app -> dist\Titanium\)
;   iscc packaging\installer.iss                (-> dist\TitaniumSetup.exe)
;
; Two install types:
;   standalone : copies the bundled app (own Python inside, nothing else needed)
;   system     : copies the source and builds a private .venv with YOUR Python 3.11+

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{4D750ED1-820D-49F6-B553-ABE0739B505B}
AppName=Titanium
AppVersion={#MyAppVersion}
AppPublisher=Quant Open Source Programme
DefaultDirName={localappdata}\Programs\Titanium
DefaultGroupName=Titanium
; The app used to be called Strategy Lab (same AppId, so this upgrades it in place).
UsePreviousGroup=no
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=TitaniumSetup
SetupIconFile=assets\titanium.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\titanium.ico

[Types]
Name: "standalone"; Description: "Standalone: includes its own Python (bigger, nothing else needed)"
Name: "system"; Description: "Use my installed Python 3.11+ (smaller; sets up a private environment with pip)"

[Components]
Name: "bundled"; Description: "Titanium with bundled Python"; Types: standalone; Flags: exclusive
Name: "source"; Description: "Titanium using your installed Python"; Types: system; Flags: exclusive

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; standalone
Source: "..\dist\Titanium\*"; DestDir: "{app}\Titanium"; Components: bundled; Flags: recursesubdirs ignoreversion
; use-my-Python: the source tree
Source: "..\honestbt\*"; DestDir: "{app}\honestbt"; Components: source; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Components: source; Flags: ignoreversion
Source: "assets\titanium.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Titanium"; Filename: "{app}\Titanium\Titanium.exe"; AppUserModelID: "QuantOpenSource.Titanium"; Components: bundled
Name: "{autodesktop}\Titanium"; Filename: "{app}\Titanium\Titanium.exe"; AppUserModelID: "QuantOpenSource.Titanium"; Components: bundled; Tasks: desktopicon
Name: "{group}\Titanium"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m honestbt.desktop"; WorkingDir: "{app}"; IconFilename: "{app}\titanium.ico"; AppUserModelID: "QuantOpenSource.Titanium"; Components: source
Name: "{autodesktop}\Titanium"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m honestbt.desktop"; WorkingDir: "{app}"; IconFilename: "{app}\titanium.ico"; AppUserModelID: "QuantOpenSource.Titanium"; Components: source; Tasks: desktopicon
Name: "{group}\Uninstall Titanium"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Titanium\Titanium.exe"; Description: "Open Titanium"; Components: bundled; Flags: nowait postinstall skipifsilent
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m honestbt.desktop"; WorkingDir: "{app}"; Description: "Open Titanium"; Components: source; Flags: nowait postinstall skipifsilent

[InstallDelete]
; leftovers from when the app was called Strategy Lab
Type: filesandordirs; Name: "{app}\StrategyLab"
Type: files; Name: "{userprograms}\Strategy Lab\Strategy Lab.lnk"
Type: files; Name: "{userprograms}\Strategy Lab\Uninstall Strategy Lab.lnk"
Type: dirifempty; Name: "{userprograms}\Strategy Lab"
Type: files; Name: "{autodesktop}\Strategy Lab.lnk"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\honestbt"
Type: files; Name: "{app}\install.log"

[Code]
var
  PyCmd, PyPrefix: String;

function TryPython(Cmd, Prefix: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(Cmd, Prefix + ' -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"',
                 '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if Result then begin
    PyCmd := Cmd;
    PyPrefix := Prefix;
  end;
end;

function FindPython(): Boolean;
begin
  Result := TryPython('py', '-3') or TryPython('python', '') or TryPython('python3', '');
end;

function NoPythonMessage(): String;
begin
  Result := 'Python 3.11 or newer was not found on this computer (tried "py -3" and "python").' + #13#10 +
            'Install it from python.org (tick "Add python.exe to PATH"), or go Back and choose the Standalone option.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectComponents) and WizardIsComponentSelected('source') and not FindPython() then begin
    MsgBox(NoPythonMessage(), mbError, MB_OK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if WizardIsComponentSelected('source') and not FindPython() then
    Result := NoPythonMessage();
end;

function RunLogged(Desc, CmdLine: String): Boolean;
var
  Code: Integer;
  Log: String;
begin
  WizardForm.StatusLabel.Caption := Desc;
  Log := ExpandConstant('{app}\install.log');
  Result := Exec(ExpandConstant('{cmd}'), '/c "' + CmdLine + ' >> "' + Log + '" 2>&1"',
                 ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  App, VenvPy: String;
begin
  if (CurStep <> ssPostInstall) or not WizardIsComponentSelected('source') then
    Exit;
  App := ExpandConstant('{app}');
  VenvPy := App + '\.venv\Scripts\python.exe';
  if not FindPython() then begin
    MsgBox(NoPythonMessage(), mbError, MB_OK);
    Exit;
  end;
  if not (RunLogged('Creating a private Python environment...',
            '"' + PyCmd + '" ' + PyPrefix + ' -m venv "' + App + '\.venv"')
          and RunLogged('Updating pip...', '"' + VenvPy + '" -m pip install --upgrade pip')
          and RunLogged('Downloading and installing numpy, pandas and Qt (a few minutes)...',
            '"' + VenvPy + '" -m pip install -e ".[desktop]"')) then
    MsgBox('Setting up the Python environment failed. Details are in:' + #13#10 + App + '\install.log',
           mbError, MB_OK);
end;
