@echo off
REM CIC Incorporation Document Extraction Pipeline
REM Run from: C:\Users\diarm\Dropbox\cic-incorporation-project
REM
REM Usage:
REM   run_extraction.bat                    - Run on 1% sample (default)
REM   run_extraction.bat --full             - Run on all documents
REM   run_extraction.bat --sample 5         - Run on 5% sample
REM   run_extraction.bat --help             - Show help

setlocal EnableDelayedExpansion

REM === CONFIGURATION ===
set "PROJECT_DIR=C:\Users\diarm\Dropbox\cic-incorporation-project"
set "DATA_DIR=C:\Users\diarm\Dropbox\companies-house-data-collection"
set "INPUT_DIR=%DATA_DIR%\data\output\incorporation_pdfs"
set "OUTPUT_DIR=%PROJECT_DIR%\data\output"
set "WORKERS=6"
set "SAMPLE_PERCENT=1"
set "SAMPLE_N="
set "CUSTOM_INPUT="

REM === PARSE ARGUMENTS ===
:parse_args
if "%~1"=="" goto run
if /i "%~1"=="--help" goto help
if /i "%~1"=="-h" goto help
if /i "%~1"=="--full" (
    set "SAMPLE_PERCENT=100"
    shift
    goto parse_args
)
if /i "%~1"=="--sample" (
    set "SAMPLE_PERCENT=%~2"
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--sample-n" (
    set "SAMPLE_N=%~2"
    shift
    shift
    goto parse_args
)
if /i "%~1"=="-n" (
    set "SAMPLE_N=%~2"
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--workers" (
    set "WORKERS=%~2"
    shift
    shift
    goto parse_args
)
if /i "%~1"=="-w" (
    set "WORKERS=%~2"
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--input" (
    set "CUSTOM_INPUT=%~2"
    shift
    shift
    goto parse_args
)
if /i "%~1"=="-i" (
    set "CUSTOM_INPUT=%~2"
    shift
    shift
    goto parse_args
)
shift
goto parse_args

:help
echo.
echo CIC Incorporation Document Extraction Pipeline
echo ===============================================
echo.
echo Usage: run_extraction.bat [OPTIONS]
echo.
echo Options:
echo   --sample N      Process N%% random sample (default: 1%%)
echo   --sample-n N    Process exactly N random documents
echo   -n N            Alias for --sample-n
echo   --full          Process all documents (100%%)
echo   --workers N     Number of parallel workers (default: 6)
echo   -w N            Alias for --workers
echo   --input PATH    Use custom input folder (skip sampling)
echo   -i PATH         Alias for --input
echo   --help, -h      Show this help message
echo.
echo Directories:
echo   Input:  %INPUT_DIR%
echo   Output: %OUTPUT_DIR%
echo.
echo Examples:
echo   run_extraction.bat                     Process 1%% sample (~65 docs)
echo   run_extraction.bat --sample 5          Process 5%% sample (~325 docs)
echo   run_extraction.bat --sample-n 50       Process exactly 50 random docs
echo   run_extraction.bat --full -w 8         Process all with 8 workers
echo   run_extraction.bat --input data\sample_25docs  Rerun on specific folder
echo.
goto end

:run
REM === COUNT INPUT FILES ===
echo.
echo ============================================================
echo CIC Incorporation Document Extraction Pipeline
echo ============================================================
echo.

cd /d "%PROJECT_DIR%"

REM Check if custom input folder is specified
if defined CUSTOM_INPUT (
    REM Use custom input folder directly - skip sampling
    set "RUN_INPUT=!CUSTOM_INPUT!"

    REM Count PDFs in custom input
    for /f %%i in ('python -c "from pathlib import Path; print(len(list(Path(r'!CUSTOM_INPUT!').glob('*.pdf'))))"') do set PDF_COUNT=%%i

    echo Using custom input folder: !CUSTOM_INPUT!
    echo Found !PDF_COUNT! PDF files
    echo Workers: %WORKERS%
    echo.
    goto :start_extraction
)

REM Count PDFs using Python (more reliable on Windows)
for /f %%i in ('python -c "from pathlib import Path; print(len(list(Path(r'%INPUT_DIR%').glob('*.pdf'))))"') do set PDF_COUNT=%%i

echo Found %PDF_COUNT% PDF files in input directory

REM Calculate sample size - use SAMPLE_N if set, otherwise use percentage
if defined SAMPLE_N (
    set "SAMPLE_SIZE=!SAMPLE_N!"
    set "SAMPLE_MODE=count"
    echo Sample: !SAMPLE_N! documents ^(fixed count^)
) else (
    set /a SAMPLE_SIZE=!PDF_COUNT! * %SAMPLE_PERCENT% / 100
    if !SAMPLE_SIZE! LSS 1 set SAMPLE_SIZE=1
    set "SAMPLE_MODE=percent"
    echo Sample: %SAMPLE_PERCENT%%% = ~!SAMPLE_SIZE! documents
)
echo Workers: %WORKERS%
echo.

REM === CREATE SAMPLE OR USE FULL ===
if defined SAMPLE_N (
    echo Creating random sample of %SAMPLE_N% documents...

    set "SAMPLE_DIR=%PROJECT_DIR%\data\sample_%SAMPLE_N%docs"

    REM Remove old sample directory if exists
    if exist "!SAMPLE_DIR!" rmdir /s /q "!SAMPLE_DIR!"

    REM Create sample using Python script
    python scripts\create_sample.py "%INPUT_DIR%" "!SAMPLE_DIR!" %SAMPLE_N%

    set "RUN_INPUT=!SAMPLE_DIR!"
) else if %SAMPLE_PERCENT% LSS 100 (
    echo Creating random sample...

    set "SAMPLE_DIR=%PROJECT_DIR%\data\sample_%SAMPLE_PERCENT%pct"

    REM Remove old sample directory if exists
    if exist "!SAMPLE_DIR!" rmdir /s /q "!SAMPLE_DIR!"

    REM Create sample using Python script
    python scripts\create_sample.py "%INPUT_DIR%" "!SAMPLE_DIR!" !SAMPLE_SIZE!

    set "RUN_INPUT=!SAMPLE_DIR!"
) else (
    set "RUN_INPUT=%INPUT_DIR%"
)

:start_extraction

echo.
echo Input directory: !RUN_INPUT!
echo Output directory: %OUTPUT_DIR%
echo.
echo Starting extraction...
echo ============================================================
echo.

REM === RUN PIPELINE ===
python src\pipeline.py "!RUN_INPUT!" -o "%OUTPUT_DIR%" -w %WORKERS%

REM Get the most recent output folder
for /f %%d in ('dir /b /ad /o-d "%OUTPUT_DIR%" 2^>nul ^| findstr /r "^[0-9][0-9][0-9][0-9]-"') do (
    set "FINAL_OUTPUT=%OUTPUT_DIR%\%%d"
    goto :done_pipeline
)

:done_pipeline

echo.
echo ============================================================
echo Extraction complete!
echo ============================================================

REM === SHOW OUTPUT LOCATION ===
echo.
echo Output saved to: !FINAL_OUTPUT!
echo.
echo Next steps:
echo   1. Check the output folder: !FINAL_OUTPUT!
echo   2. Review batch_summary.json for statistics
echo   3. Run: python scripts\evaluate.py --input "!FINAL_OUTPUT!" --stats
echo.

:end
endlocal
