@echo off
REM Run ControlMe Maya integration tests via mayapy.
REM Usage:
REM   run_maya_tests.bat               -- run all Maya tests
REM   run_maya_tests.bat -k test_name  -- run a specific test
REM   run_maya_tests.bat --tb=short    -- shorter tracebacks

set MAYA_PATH=C:\Program Files\Autodesk\Maya2026\bin
set REPO_ROOT=%~dp0..

"%MAYA_PATH%\mayapy.exe" -m pytest "%REPO_ROOT%\tests\maya" -v %*
