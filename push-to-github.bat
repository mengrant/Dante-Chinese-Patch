@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Target : https://github.com/mengrant/dante-chinese-fix.git
echo Branch : master
echo.
echo A GitHub sign-in window will open on first push. Log in once and
echo Git Credential Manager will remember it for this machine.
echo.
git push -u origin master
echo.
echo git exit code: %ERRORLEVEL%
pause
