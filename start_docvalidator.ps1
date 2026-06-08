# start_docvalidator.ps1
# Starts BOTH backends and the frontend.
#
#  Port 8000 — Original backend (Supabase: Dashboard, Database, Audit, Users)
#  Port 8001 — backend_v2 OCR engine (PaddleOCR: Extraction Studio)
#  Port 5173 — React frontend
#
# Usage:  Right-click -> Run with PowerShell
#         OR from any terminal: .\start_docvalidator.ps1

$ROOT      = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND   = Join-Path $ROOT "backend"
$BACKEND_V2 = Join-Path $ROOT "backend_v2"
$FRONTEND  = Join-Path $ROOT "react-frontend"

Write-Host ""
Write-Host "DocValidator — Starting All Services" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan

# ── 1. Kill old instances ─────────────────────────────────────────────────────
Write-Host "Stopping any existing Python processes..." -ForegroundColor Gray
Get-Process -Name "python" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800

# ── 2. Start Original Backend (Supabase) on port 8000 ─────────────────────────
Write-Host "Starting Supabase backend on http://127.0.0.1:8000 ..." -ForegroundColor Yellow

$backendCmd = @"
cd '$BACKEND'
Write-Host 'Supabase backend starting on port 8000...' -ForegroundColor Cyan
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Write-Host 'Backend stopped.' -ForegroundColor Red
Read-Host 'Press Enter to close'
"@

Start-Process powershell.exe `
    -ArgumentList "-NoExit", "-Command", $backendCmd `
    -WindowStyle Normal `
    -WorkingDirectory $BACKEND

Write-Host "  Supabase backend launched." -ForegroundColor Green
Start-Sleep -Seconds 5

# ── 3. Start Backend V2 (PaddleOCR) on port 8001 ──────────────────────────────
Write-Host "Starting backend_v2 OCR engine on http://127.0.0.1:8001 ..." -ForegroundColor Yellow

$backendV2Cmd = @"
cd '$BACKEND_V2'
Write-Host 'backend_v2 OCR engine starting on port 8001...' -ForegroundColor Cyan
venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
Write-Host 'backend_v2 stopped.' -ForegroundColor Red
Read-Host 'Press Enter to close'
"@

Start-Process powershell.exe `
    -ArgumentList "-NoExit", "-Command", $backendV2Cmd `
    -WindowStyle Normal `
    -WorkingDirectory $BACKEND_V2

Write-Host "  backend_v2 OCR engine launched." -ForegroundColor Green
Start-Sleep -Seconds 5

# ── 5. Start Frontend ─────────────────────────────────────────────────────────
Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Yellow

$frontendCmd = @"
cd '$FRONTEND'
Write-Host 'Frontend starting...' -ForegroundColor Cyan
npm run dev
Write-Host 'Frontend stopped.' -ForegroundColor Red
Read-Host 'Press Enter to close'
"@

Start-Process powershell.exe `
    -ArgumentList "-NoExit", "-Command", $frontendCmd `
    -WindowStyle Normal `
    -WorkingDirectory $FRONTEND

Write-Host "  Frontend launched." -ForegroundColor Green

# ── 6. Open browser ───────────────────────────────────────────────────────────
Start-Sleep -Seconds 5
Write-Host "Opening browser..." -ForegroundColor Gray
Start-Process "http://localhost:5173/dashboard"

Write-Host ""
Write-Host "All services running!" -ForegroundColor Green
Write-Host "  Supabase Backend : http://127.0.0.1:8000  (Dashboard, Database, Audit)" -ForegroundColor White
Write-Host "  Frontend         : http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "Close the terminal windows to stop services." -ForegroundColor Gray
