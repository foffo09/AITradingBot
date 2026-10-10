@echo off
SETLOCAL
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Errore: ambiente virtuale non trovato. Creare prima la cartella .venv oppure usare un interprete Python compatibile.
    echo Esempio: py -m venv .venv
    exit /b 1
)

call ".venv\Scripts\python.exe" -m streamlit run app.py
ENDLOCAL
