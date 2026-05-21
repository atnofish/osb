@echo off
REM OSB 自动化配置工具 - 一键运行脚本
REM 按顺序执行：JDBC 数据源 -> JMS 初始化 -> DBAdapter 配置

echo ============================================
echo OSB 自动化配置工具
echo ============================================
echo.

set WLST_HOME=C:\Oracle\Jdeveloper12c\Oracle\Middleware\oracle_common\common\bin
set CONFIG=%~dp0config.yaml

if not exist "%CONFIG%" (
    echo [ERROR] 找不到配置文件: %CONFIG%
    pause
    exit /b 1
)

echo [1/3] 配置 JDBC 数据源...
"%WLST_HOME%\wlst.bat" "%~dp0wls\scripts\create_datasource.py" "%CONFIG%"
if errorlevel 1 (
    echo [ERROR] JDBC 数据源配置失败
    pause
    exit /b 1
)

echo.
echo [2/3] 初始化 JMS 配置...
"%WLST_HOME%\wlst.bat" "%~dp0wls\scripts\setup_jms.py" "%CONFIG%"
if errorlevel 1 (
    echo [ERROR] JMS 初始化失败
    pause
    exit /b 1
)

echo.
echo [3/3] 配置 DBAdapter...
"%WLST_HOME%\wlst.bat" "%~dp0wls\scripts\configure_dbadapter.py" "%CONFIG%"
if errorlevel 1 (
    echo [ERROR] DBAdapter 配置失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo 所有配置完成！
echo ============================================
pause
