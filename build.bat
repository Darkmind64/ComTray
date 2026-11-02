@echo off
cd /d "%~dp0"
python -m pip install -q pystray pillow pyserial pyinstaller
rem Version installee (dossier : demarrage rapide)
python -m PyInstaller --noconfirm --onedir --noconsole --icon comtray.ico --name ComTray --distpath dist\app --workpath build\app comtray.py
rem Version portable (fichier unique)
python -m PyInstaller --noconfirm --onefile --noconsole --icon comtray.ico --name ComTray --distpath dist --workpath build\one comtray.py
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ISCC%" ("%ISCC%" ComTray.iss) else (echo Inno Setup 6 introuvable : installateur non genere)
