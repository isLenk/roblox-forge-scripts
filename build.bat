@echo off
pyinstaller --onefile --uac-admin --name LENK.TOOLS --noconsole --collect-all cv2 circle_bot.py
echo.
echo Built: dist\LENK.TOOLS.exe
pause
