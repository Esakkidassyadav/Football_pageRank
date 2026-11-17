@echo off
REM One-click start for Windows.
REM First time: creates a private Python environment and installs the libraries,
REM then opens the website in your browser. Close this window to stop it.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org
    echo and tick "Add python.exe to PATH" during the installation.
    pause
    exit /b 1
)

if not exist venv\Scripts\python.exe (
    echo Creating a private Python environment in the "venv" folder...
    python -m venv venv
    if errorlevel 1 goto fail
)

call venv\Scripts\activate.bat

echo Installing the libraries - slow only the first time...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 goto fail

if not exist data\passes.csv.gz (
    echo.
    echo The data files are missing. Downloading them from StatsBomb - about 650 MB, a few minutes...
    python data_prep.py
    if errorlevel 1 goto fail
)

echo.
echo Starting the website. It opens in your browser at http://localhost:5000
echo Close this window to stop it.
python app.py
goto end

:fail
echo.
echo Something went wrong. Read the messages above.
pause
exit /b 1

:end
