@echo off
setlocal
cd /d "%~dp0"
title Rukomeza Market - serveur local

echo ============================================================
echo   Rukomeza Market - lancement local
echo ============================================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERREUR] Environnement virtuel introuvable : venv\Scripts\python.exe
    echo.
    echo Creez-le avec :
    echo    python -m venv venv
    echo    venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo [1/3] Application des migrations...
"venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 goto error

echo.
echo [2/3] Verification des donnees de demonstration...
"venv\Scripts\python.exe" manage.py seed_demo
if errorlevel 1 goto error

echo.
echo [3/3] Demarrage du serveur sur http://127.0.0.1:8000/
echo.
echo   Admin   : admin / Admin#2026
echo   Client  : amina@example.com / Customer#2026
echo   Vendeur : greenbasket@example.com / Seller#2026
echo.
echo   Pour arreter : Ctrl+C dans cette fenetre.
echo.

start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:8000/'"
"venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
goto end

:error
echo.
echo [ERREUR] Le lancement a echoue. Lisez le message ci-dessus.
pause
exit /b 1

:end
echo.
echo Serveur arrete.
pause
