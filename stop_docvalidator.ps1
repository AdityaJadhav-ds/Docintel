# stop_docvalidator.ps1
# Cleanly stops backend (Python/uvicorn) and frontend (Node/Vite).
# Run this when you want to shut everything down.

Write-Host ""
Write-Host "DocValidator — Stopping All Services" -ForegroundColor Yellow
Write-Host "=====================================" -ForegroundColor Yellow

$stopped = 0

# Stop Python/uvicorn (backend)
$py = Get-Process -Name "python" -ErrorAction SilentlyContinue
if ($py) {
    $py | Stop-Process -Force
    Write-Host "  Backend (Python) stopped." -ForegroundColor Green
    $stopped++
} else {
    Write-Host "  Backend: not running." -ForegroundColor Gray
}

# Stop Node/Vite (frontend) — only kill npm/vite related nodes
$nodes = Get-Process -Name "node" -ErrorAction SilentlyContinue
if ($nodes) {
    $nodes | Stop-Process -Force
    Write-Host "  Frontend (Node) stopped." -ForegroundColor Green
    $stopped++
} else {
    Write-Host "  Frontend: not running." -ForegroundColor Gray
}

Write-Host ""
if ($stopped -gt 0) {
    Write-Host "All services stopped." -ForegroundColor Green
} else {
    Write-Host "Nothing was running." -ForegroundColor Gray
}
Write-Host ""
