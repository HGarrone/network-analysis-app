@echo off
cd /d "%~dp0"
cls
color 1F

echo ========================================================
echo  SETUP AUTOMATICO  NETWORK ANALYSIS
echo ========================================================
echo.

:: ── STEP 1: ambiente virtuale .venv_win gia' presente? ───────────────────────
if exist ".venv_win\Scripts\python.exe" (
    echo  [OK] Ambiente virtuale Windows trovato in .venv_win.
    goto :ICONA
)

:: ── STEP 2: cerca un interprete Python sul sistema (py launcher o python) ────
echo  [INFO] Creazione ambiente virtuale .venv_win...
echo.

set PYEXE=
where py >nul 2>&1
if %errorlevel% equ 0 (
    set PYEXE=py
) else (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set PYEXE=python
    )
)

if "%PYEXE%"=="" (
    color 4F
    echo  [ERRORE] Nessun interprete Python trovato sul sistema.
    echo  Installa Python da https://www.python.org/downloads/ e riprova.
    pause
    exit /b
)

echo  [STEP 1/3] Creazione ambiente virtuale con "%PYEXE%"...
%PYEXE% -m venv .venv_win
if not exist ".venv_win\Scripts\python.exe" (
    color 4F
    echo  [ERRORE] Creazione ambiente virtuale fallita.
    pause
    exit /b
)

echo  [STEP 2/3] Aggiornamento pip...
".venv_win\Scripts\python.exe" -m pip install --upgrade pip -q

echo  [STEP 3/3] Installazione librerie da requirements.txt...
echo  (Potrebbe richiedere qualche minuto...)
".venv_win\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo  [OK] Ambiente virtuale creato con successo!
echo.

:: ── Creazione icona ───────────────────────────────────────────────────────────
:ICONA
echo ========================================================
echo  CREAZIONE COLLEGAMENTO DESKTOP
echo ========================================================
echo.

if not exist "assets\icona.ico" (
    if exist "assets\crea_icona.py" (
        ".venv_win\Scripts\python.exe" assets\crea_icona.py
    )
)

echo  Sto creando l'icona "Network Analysis" sul Desktop...

if exist "assets\installazione.ps1" (
    PowerShell -NoProfile -ExecutionPolicy Bypass -File "assets\installazione.ps1"
) else (
    echo  [AVVISO] Script icona non trovato. Provo metodo base...
    powershell "$s=(New-Object -COM WScript.Shell).CreateShortcut('%userprofile%\Desktop\Network Analysis.lnk');$s.TargetPath='wscript.exe';$s.Arguments='\""%~dp0assets\run_hidden.vbs\""';$s.IconLocation='%~dp0assets\icona.ico';$s.WorkingDirectory='%~dp0';$s.Save()"
)

echo.
echo ========================================================
echo  INSTALLAZIONE COMPLETATA!
echo  Ora puoi avviare l'app dall'icona "Network Analysis" sul Desktop.
echo  L'app si aprira' nel browser predefinito.
echo ========================================================
echo.
pause
