@echo off
echo ========================================
echo   AI-Router-Lite 虚拟环境配置脚本
echo ========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未安装或未添加到 PATH
    echo 请访问 https://www.python.org/ 下载安装 Python 3.8+
    pause
    exit /b 1
)

echo [1/3] 创建虚拟环境...
python -m venv venv

echo [2/3] 激活虚拟环境...
call venv\Scripts\activate.bat

echo [3/3] 安装依赖...
pip install -r requirements.txt

echo.
echo ========================================
echo   安装完成！
echo   激活虚拟环境: venv\Scripts\activate
echo   启动服务: python main.py
echo ========================================
pause