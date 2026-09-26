param(
    [string]$Message = "Update Reef AI Hub"
)

$ErrorActionPreference = "Stop"

Write-Host "`n=== Reef AI Hub Git Save ===" -ForegroundColor Cyan

git status

Write-Host "`nStaging changes..." -ForegroundColor Yellow
git add .

Write-Host "`nChanges to commit:" -ForegroundColor Yellow
git status

Write-Host "`nCommitting..." -ForegroundColor Yellow
git commit -m $Message

Write-Host "`nPushing to origin/main..." -ForegroundColor Yellow
git push origin main

Write-Host "`n=== Done ===" -ForegroundColor Green
git status