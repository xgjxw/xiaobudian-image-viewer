@echo off
setlocal
cd /d %~dp0

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name xiaobudian-image-viewer ^
  run.py

echo.
echo Build finished.
echo EXE: %~dp0dist\xiaobudian-image-viewer.exe
endlocal

