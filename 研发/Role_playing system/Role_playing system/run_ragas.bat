@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=D:\Anaconda\envs\python_3_10\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

set "TESTSET_PATH=evals\testset_manual_extended.jsonl"
if not exist "%TESTSET_PATH%" set "TESTSET_PATH=evals\testset_manual.jsonl"

if not defined RAGAS_TESTSET_PATH set "RAGAS_TESTSET_PATH=%TESTSET_PATH%"
if not defined RAGAS_ASYNC set "RAGAS_ASYNC=0"
if not defined RAGAS_METRICS set "RAGAS_METRICS=full"
if not defined RAGAS_MAX_WORKERS set "RAGAS_MAX_WORKERS=1"

echo [RAGAS] Project Dir: %cd%
echo [RAGAS] Python: %PYTHON_EXE%
echo [RAGAS] Testset: %RAGAS_TESTSET_PATH%
echo [RAGAS] Async: %RAGAS_ASYNC%
echo [RAGAS] Metrics: %RAGAS_METRICS%
echo [RAGAS] Max Workers: %RAGAS_MAX_WORKERS%
echo.

"%PYTHON_EXE%" ".\eval_ragas_019.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo [RAGAS] Finished successfully.
    echo [RAGAS] Result CSV: evals\ragas_result_019.csv
    echo [RAGAS] Input JSONL: evals\ragas_inputs_019.jsonl
) else (
    echo [RAGAS] Failed with exit code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
