@echo off
REM RegimeEngine — Windows Task Scheduler setup
REM Run this script ONCE as Administrator to register the three daily tasks.
REM All tasks run Mon–Fri only. Adjust the Python path if your venv differs.

set PYTHON=python
set ROOT=D:\Synaptic\MasterTradingLogic\RegimeEngine

echo Creating RegimeEngine_Evening task (18:00 weekdays)...
schtasks /create /tn "RegimeEngine_Evening" /tr "%PYTHON% %ROOT%\automation\evening_runner.py" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:00 /f

echo Creating RegimeEngine_Morning task (09:10 weekdays)...
schtasks /create /tn "RegimeEngine_Morning" /tr "%PYTHON% %ROOT%\automation\morning_monitor.py" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:10 /f

echo Creating RegimeEngine_TradeWindow task (10:15 weekdays)...
schtasks /create /tn "RegimeEngine_TradeWindow" /tr "%PYTHON% %ROOT%\automation\trade_window.py" /sc weekly /d MON,TUE,WED,THU,FRI /st 10:15 /f

echo.
echo Done. Verify with: schtasks /query /tn "RegimeEngine_Evening"
echo To remove: schtasks /delete /tn "RegimeEngine_Evening" /f
