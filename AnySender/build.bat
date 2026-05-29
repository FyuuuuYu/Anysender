@echo off
chcp 65001 >nul
title AnySender 一键打包

echo ============================================
echo   AnySender — 一键打包脚本
echo ============================================
echo.

cd /d "%~dp0"

:: 1. 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    pause & exit /b 1
)

:: 2. 检查 / 安装依赖
echo [1/3] 检查依赖...
python deps\setup.py --check 2>nul | findstr "DEPS_READY" >nul
if %errorlevel% neq 0 (
    echo [1/3] 正在安装缺失依赖...
    python deps\setup.py
) else (
    echo [1/3] 依赖已就绪
)

:: 3. 检查 PyInstaller
python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [2/3] 安装 PyInstaller...
    pip install pyinstaller
)
echo [2/3] PyInstaller 已就绪

:: 4. 打包
echo [3/3] 开始打包...
pyinstaller AnySender.spec --noconfirm

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo   打包成功！输出目录：dist\
    echo   可执行文件：dist\AnySender.exe
    echo ============================================
) else (
    echo.
    echo [错误] 打包失败，请检查上方输出
)

pause
