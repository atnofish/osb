@echo off
REM OSB 项目骨架生成器 - 运行脚本

echo ============================================
echo OSB 项目骨架生成器
echo ============================================
echo.

set CONFIG=%~dp0config.yaml
set OUTPUT=%~dp0generated_projects

if not exist "%CONFIG%" (
    echo [ERROR] 找不到配置文件: %CONFIG%
    pause
    exit /b 1
)

python "%~dp0python\generate_project.py" "%CONFIG%" "%OUTPUT%"

echo.
echo ============================================
echo 项目骨架已生成到: %OUTPUT%
echo ============================================
pause
