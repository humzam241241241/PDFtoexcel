@echo off
title B92_ALPO PDF Extractor
color 0A
echo.
echo  ============================================
echo     B92_ALPO Monitoring Report Extractor
echo  ============================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python 3.10+ and add it to PATH.
    echo.
    pause
    exit /b 1
)

:: Install dependencies if needed
echo  Checking dependencies...
pip show pdfplumber >nul 2>&1
if errorlevel 1 (
    echo  Installing required packages...
    pip install -r "%~dp0requirements.txt"
    echo.
)

:MENU
echo.
echo  Select mode:
echo.
echo    [1] Process a single PDF file
echo    [2] Process all PDFs in a folder
echo    [3] Exit
echo.
set /p CHOICE="  Enter choice (1/2/3): "

if "%CHOICE%"=="1" goto SINGLE
if "%CHOICE%"=="2" goto BATCH
if "%CHOICE%"=="3" goto END
echo  Invalid choice. Try again.
goto MENU

:SINGLE
echo.
set /p PDF_FILE="  Drag and drop your PDF here (or type the full path): "
:: Strip surrounding quotes if present
set PDF_FILE=%PDF_FILE:"=%
if not exist "%PDF_FILE%" (
    echo  [ERROR] File not found: %PDF_FILE%
    goto MENU
)
set /p OUT_FILE="  Output CSV name [b92_output.csv]: "
if "%OUT_FILE%"=="" set OUT_FILE=b92_output.csv

echo.
echo  Processing...
python "%~dp0extract_b92.py" "%PDF_FILE%" -o "%OUT_FILE%" -v
echo.
echo  Done. Output: %OUT_FILE%
goto AGAIN

:BATCH
echo.
set /p PDF_DIR="  Enter folder path containing PDFs: "
set PDF_DIR=%PDF_DIR:"=%
if not exist "%PDF_DIR%\" (
    echo  [ERROR] Folder not found: %PDF_DIR%
    goto MENU
)
set /p OUT_FILE="  Output CSV name [b92_output.csv]: "
if "%OUT_FILE%"=="" set OUT_FILE=b92_output.csv

echo.
echo  Processing all PDFs in: %PDF_DIR%
python "%~dp0extract_b92.py" "%PDF_DIR%" -o "%OUT_FILE%" -v
echo.
echo  Done. Output: %OUT_FILE%
goto AGAIN

:AGAIN
echo.
set /p REPEAT="  Process another? (Y/N): "
if /i "%REPEAT%"=="Y" goto MENU

:END
echo.
echo  Goodbye.
echo.
pause
