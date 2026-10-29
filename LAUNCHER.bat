@echo off
cd /d "%~dp0"

:: 0. Chiude un'eventuale istanza precedente dell'app ancora in esecuzione:
::    senza questo, un doppio click quando l'app e' gia' aperta prova a
::    legarsi alla porta 8501 gia' occupata e resta bloccato in silenzio
::    (pythonw non ha una console: non si vede alcun errore ne' si apre
::    il browser). Cosi' l'icona apre sempre un'istanza pulita e aggiornata.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gui_app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
:: pausa breve senza dipendere da una console reale (timeout.exe fallisce se
:: lo stdin non e' un terminale, come qui: avviato da wscript senza console)
ping -n 2 127.0.0.1 >nul

:: 1. Ambiente virtuale Windows dedicato (creato da PRIMO_AVVIO.bat)
if exist ".venv_win\Scripts\pythonw.exe" (
    start "" ".venv_win\Scripts\pythonw.exe" -m streamlit run gui_app.py --server.headless false > streamlit_log.txt 2>&1
    exit /b
)

:: 2. Python di sistema
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python non trovato. Esegui PRIMO_AVVIO.bat
    pause
    exit /b
)

start "" pythonw -m streamlit run gui_app.py --server.headless false > streamlit_log.txt 2>&1
