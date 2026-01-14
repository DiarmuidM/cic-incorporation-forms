@echo off
setlocal

set SERVER=root@157.245.37.136
set LOCAL_DIR=C:\Users\diarm\Dropbox\cic-incorporation-project
set REMOTE_DIR=~/cic-incorporation-docs

if "%1"=="" goto help
if "%1"=="connect" goto connect
if "%1"=="status" goto status
if "%1"=="upload-code" goto uploadcode
if "%1"=="setup" goto setup
if "%1"=="start" goto start
if "%1"=="logs" goto logs
if "%1"=="download" goto download
if "%1"=="download-input" goto downloadinput
goto help

:connect
echo Connecting to server...
ssh %SERVER%
goto end

:status
echo.
echo CIC Extraction Status
echo =====================
echo.
echo Screen sessions:
ssh %SERVER% "screen -ls 2>/dev/null || echo 'No screen sessions'"
echo.
echo Recent log output:
ssh %SERVER% "tail -20 %REMOTE_DIR%/logs/extraction.log 2>/dev/null || echo 'No extraction log found'"
echo.
echo Output folders:
ssh %SERVER% "ls -la %REMOTE_DIR%/data/output/ 2>/dev/null | head -10 || echo 'No output folders yet'"
echo.
echo Input PDFs:
ssh %SERVER% "ls %REMOTE_DIR%/data/input/*.pdf 2>/dev/null | wc -l" 2>nul
goto end

:uploadcode
echo.
echo Uploading extraction code to server...
echo.

REM Create remote directories
ssh %SERVER% "mkdir -p %REMOTE_DIR%/{src,scripts,logs,data/{input,output}}"

REM Upload source files
echo Uploading src/ folder...
scp "%LOCAL_DIR%\src\*.py" %SERVER%:%REMOTE_DIR%/src/

echo Uploading scripts/ folder...
scp "%LOCAL_DIR%\scripts\create_sample.py" %SERVER%:%REMOTE_DIR%/scripts/
scp "%LOCAL_DIR%\scripts\evaluate.py" %SERVER%:%REMOTE_DIR%/scripts/

echo Uploading evaluation modules...
ssh %SERVER% "mkdir -p %REMOTE_DIR%/src/evaluation"
scp "%LOCAL_DIR%\src\evaluation\*.py" %SERVER%:%REMOTE_DIR%/src/evaluation/

echo Uploading validation modules...
ssh %SERVER% "mkdir -p %REMOTE_DIR%/src/validation"
scp "%LOCAL_DIR%\src\validation\*.py" %SERVER%:%REMOTE_DIR%/src/validation/

echo Uploading shell scripts...
scp "%LOCAL_DIR%\run_extraction.sh" %SERVER%:%REMOTE_DIR%/
scp "%LOCAL_DIR%\setup_server.sh" %SERVER%:%REMOTE_DIR%/
scp "%LOCAL_DIR%\requirements-server.txt" %SERVER%:%REMOTE_DIR%/

REM Make scripts executable
ssh %SERVER% "chmod +x %REMOTE_DIR%/*.sh"

echo.
echo Done! Code uploaded to %SERVER%:%REMOTE_DIR%
echo.
echo Next: Run 'server setup' to install dependencies (first time only)
goto end

:setup
echo.
echo Setting up extraction environment on server...
echo.
ssh %SERVER% "cd %REMOTE_DIR% && ./setup_server.sh"
echo.
echo Setup complete!
goto end

:start
echo.
echo Start CIC Document Extraction
echo =============================
echo.

REM Check how many PDFs are available
echo Checking input PDFs...
for /f %%i in ('ssh %SERVER% "ls %REMOTE_DIR%/data/input/*.pdf 2>/dev/null | wc -l"') do set PDF_COUNT=%%i
echo Found %PDF_COUNT% PDFs in input folder.
echo.

set /p workers="Number of workers (1-2, default 1): "
if "%workers%"=="" set workers=1
echo Using %workers% worker(s)
echo.

echo Options:
echo   1. Run on 1%% sample
echo   2. Run on 5%% sample
echo   3. Run on 10%% sample
echo   4. Run on specific number of documents
echo   5. Run on ALL documents
echo   0. Cancel
echo.
set /p extchoice="Enter choice (0-5): "

if "%extchoice%"=="1" goto ext_1pct
if "%extchoice%"=="2" goto ext_5pct
if "%extchoice%"=="3" goto ext_10pct
if "%extchoice%"=="4" goto ext_custom
if "%extchoice%"=="5" goto ext_full
if "%extchoice%"=="0" goto end
echo Invalid choice
goto end

:ext_1pct
echo.
echo Starting 1%% sample extraction in background...
ssh %SERVER% "screen -dmS extraction bash -c 'cd %REMOTE_DIR% && source venv/bin/activate && ./run_extraction.sh --sample 1 -w %workers% 2>&1 | tee logs/extraction.log'"
goto ext_started

:ext_5pct
echo.
echo Starting 5%% sample extraction in background...
ssh %SERVER% "screen -dmS extraction bash -c 'cd %REMOTE_DIR% && source venv/bin/activate && ./run_extraction.sh --sample 5 -w %workers% 2>&1 | tee logs/extraction.log'"
goto ext_started

:ext_10pct
echo.
echo Starting 10%% sample extraction in background...
ssh %SERVER% "screen -dmS extraction bash -c 'cd %REMOTE_DIR% && source venv/bin/activate && ./run_extraction.sh --sample 10 -w %workers% 2>&1 | tee logs/extraction.log'"
goto ext_started

:ext_custom
echo.
set /p doccount="Enter number of documents to process: "
echo.
echo Starting extraction of %doccount% documents in background...
ssh %SERVER% "screen -dmS extraction bash -c 'cd %REMOTE_DIR% && source venv/bin/activate && ./run_extraction.sh --sample-n %doccount% -w %workers% 2>&1 | tee logs/extraction.log'"
goto ext_started

:ext_full
echo.
echo WARNING: Full extraction on 2GB RAM server may be slow.
set /p confirm="Continue with full extraction? (y/n): "
if /i not "%confirm%"=="y" goto end
echo.
echo Starting full extraction in background...
ssh %SERVER% "screen -dmS extraction bash -c 'cd %REMOTE_DIR% && source venv/bin/activate && ./run_extraction.sh --full -w %workers% 2>&1 | tee logs/extraction.log'"
goto ext_started

:ext_started
echo.
echo Extraction started in background screen session!
echo.
echo Monitor with:
echo   server status    - Quick status check
echo   server logs      - View live log output
echo   server connect   - Then: screen -r extraction
echo.
goto end

:logs
echo.
echo Live extraction log (Ctrl+C to exit):
echo =====================================
ssh %SERVER% "tail -f %REMOTE_DIR%/logs/extraction.log"
goto end

:download
echo.
echo Download Extraction Results
echo ===========================
echo.
echo Available output folders on server:
ssh %SERVER% "ls -la %REMOTE_DIR%/data/output/ 2>/dev/null | grep '^d' | grep -v '\.$'"
echo.
set /p folder="Enter folder name to download (e.g., 2026-01-12_143052): "
echo.

if "%folder%"=="" (
    echo No folder specified. Cancelled.
    goto end
)

echo Creating local output directory...
if not exist "%LOCAL_DIR%\data\output\%folder%" mkdir "%LOCAL_DIR%\data\output\%folder%"

echo.
echo Downloading results from %folder%...
REM Use -T to disable filename checking
scp -r -T %SERVER%:"%REMOTE_DIR%/data/output/%folder%/*" "%LOCAL_DIR%\data\output\%folder%"

echo.
echo Done! Results downloaded to: %LOCAL_DIR%\data\output\%folder%
echo.
echo Run evaluation with:
echo   python scripts\evaluate.py --input "data\output\%folder%" --stats
goto end

:downloadinput
echo.
echo Download Input PDFs from Server
echo ================================
echo.

REM Show available data folders on server
echo Available folders in server data directory:
echo.
ssh %SERVER% "cd %REMOTE_DIR%/data && for d in */; do echo \"  $d\"; done 2>/dev/null"
echo.
set /p inputfolder="Enter folder name (e.g., input, sample_1pct): "

if "%inputfolder%"=="" (
    echo No folder specified. Cancelled.
    goto end
)

REM Check how many PDFs are in the selected folder
echo.
echo Checking %inputfolder% folder...
for /f %%i in ('ssh %SERVER% "ls %REMOTE_DIR%/data/%inputfolder%/*.pdf 2>/dev/null | wc -l"') do set PDF_COUNT=%%i
echo Found %PDF_COUNT% PDFs in %inputfolder%.
echo.

if "%PDF_COUNT%"=="0" (
    echo No PDFs found in that folder.
    goto end
)

echo Options:
echo   1. Download ALL PDFs (%PDF_COUNT% files)
echo   2. Download a specific number of PDFs
echo   0. Cancel
echo.
set /p dlchoice="Enter choice (0-2): "

if "%dlchoice%"=="0" goto end
if "%dlchoice%"=="2" goto dl_custom
if "%dlchoice%"=="1" goto dl_all
echo Invalid choice
goto end

:dl_custom
set /p dlcount="Enter number of PDFs to download: "
echo.
echo Creating local input directory...
if not exist "%LOCAL_DIR%\data\input" mkdir "%LOCAL_DIR%\data\input"
echo.
echo Downloading %dlcount% PDFs from server %inputfolder%...
REM Get list of PDFs and download first N
ssh %SERVER% "ls %REMOTE_DIR%/data/%inputfolder%/*.pdf | head -%dlcount%" > "%TEMP%\pdf_list.txt"
for /f "tokens=*" %%f in (%TEMP%\pdf_list.txt) do (
    echo Downloading: %%~nxf
    scp -T %SERVER%:"%%f" "%LOCAL_DIR%\data\input"
)
del "%TEMP%\pdf_list.txt" 2>nul
echo.
echo Done! Downloaded %dlcount% PDFs to: %LOCAL_DIR%\data\input
goto end

:dl_all
echo.
echo Creating local input directory...
if not exist "%LOCAL_DIR%\data\input" mkdir "%LOCAL_DIR%\data\input"
echo.
echo Downloading ALL %PDF_COUNT% PDFs from server %inputfolder%...
echo This may take a while...
scp -r -T %SERVER%:"%REMOTE_DIR%/data/%inputfolder%/*.pdf" "%LOCAL_DIR%\data\input"
echo.
echo Done! Downloaded PDFs to: %LOCAL_DIR%\data\input
goto end

:help
echo.
echo CIC Extraction Server Commands
echo ==============================
echo.
echo   server connect       - SSH into the server
echo   server status        - Check extraction status and output folders
echo   server upload-code   - Upload extraction code to server
echo   server setup         - Install dependencies (run once)
echo   server start         - Start extraction job (interactive menu)
echo   server logs          - View live extraction log
echo   server download      - Download extraction results
echo   server download-input - Download input PDFs to local machine
echo.
echo Workflow (server):
echo   1. Upload PDFs:  (from companies-house-data-collection) server upload-pdfs
echo   2. Upload code:  server upload-code
echo   3. Setup:        server setup  (first time only)
echo   4. Run:          server start
echo   5. Monitor:      server status / server logs
echo   6. Download:     server download
echo.
echo Workflow (local):
echo   1. Download PDFs: server download-input
echo   2. Run locally:   run_extraction.bat --sample-n 100
echo.
goto end

:end
endlocal
