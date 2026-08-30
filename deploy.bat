@echo off
chcp 65001 >nul
echo ========================================
echo  utango デプロイスクリプト
echo ========================================

:: 1. Git add & commit
echo.
echo [1/3] Git コミット...
set /p MSG="コミットメッセージを入力: "
git add .
git status
echo.
set /p CONFIRM="この内容でコミットしますか？ (y/n): "
if /i not "%CONFIRM%"=="y" (
    echo キャンセルしました。
    pause
    exit /b
)
git commit -m "%MSG%"

:: 2. GitHub に push
echo.
echo [2/3] GitHub に push...
git push origin main
if errorlevel 1 (
    echo [エラー] GitHub への push に失敗しました。
    pause
    exit /b
)
echo GitHub push 完了！

:: 3. VPS にデプロイ
echo.
echo [3/3] ConoHa VPS にデプロイ...
ssh root@133.88.121.90 "cd /opt/utango && git pull origin main && cd frontend && npm install && npm run build && cd ../backend && source venv/bin/activate && pip install -r requirements.txt && sudo systemctl restart utango"
if errorlevel 1 (
    echo [エラー] VPS デプロイに失敗しました。
    pause
    exit /b
)

echo.
echo ========================================
echo  デプロイ完了！
echo  https://utango.valueupdate.net
echo ========================================
pause
