@echo off
title Propagation Card Viewer
cd /d "%~dp0"

where Rscript >nul 2>&1
if %errorlevel%==0 (
    Rscript launch.R
    goto :end
)

if exist "C:\Program Files\R\R-4.3.1\bin\Rscript.exe" (
    "C:\Program Files\R\R-4.3.1\bin\Rscript.exe" launch.R
    goto :end
)

if exist "C:\Program Files\R\R-4.4.0\bin\Rscript.exe" (
    "C:\Program Files\R\R-4.4.0\bin\Rscript.exe" launch.R
    goto :end
)

for /d %%G in ("C:\Program Files\R\R-*") do (
    if exist "%%G\bin\Rscript.exe" (
        "%%G\bin\Rscript.exe" launch.R
        goto :end
    )
)

echo ERROR: Rscript not found. Please install R from https://cran.r-project.org
pause

:end
pause
