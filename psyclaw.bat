@echo off
REM 一键启动 PsyClaw —— 双击本文件即进入 REPL；也可命令行带参数：psyclaw.bat doctor
chcp 65001 >nul
cd /d "%~dp0"
python -m psyclaw %*
if errorlevel 1 pause
