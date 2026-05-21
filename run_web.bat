@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ============================================
echo  OSB 自动化工具 Web 端
echo ============================================
echo.
echo 启动中... 打开 http://localhost:8899
echo.
python web\app.py
pause
