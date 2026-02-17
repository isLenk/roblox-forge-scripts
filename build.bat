@echo off
pyinstaller --onefile --uac-admin --name LENK.TOOLS --noconsole --clean circle_bot.py
echo.
echo Built: dist\LENK.TOOLS.exe
pause
