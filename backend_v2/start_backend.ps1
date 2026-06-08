# start_backend.ps1
# Production backend launcher — NO --reload (reload mode halves performance)
#
# Usage:
#   cd backend_v2
#   .\start_backend.ps1
#
# For benchmarking, ALWAYS use this script, not uvicorn --reload.

Write-Host "DocValidator Backend — Production Mode" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Set CPU thread counts before Python starts
$env:OMP_NUM_THREADS = "4"
$env:MKL_NUM_THREADS = "4"

Write-Host "OMP_NUM_THREADS = $env:OMP_NUM_THREADS" -ForegroundColor Gray
Write-Host "MKL_NUM_THREADS = $env:MKL_NUM_THREADS" -ForegroundColor Gray
Write-Host ""
Write-Host "Starting uvicorn (production mode, no reload)..." -ForegroundColor Yellow
Write-Host "Backend will be available at: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host ""

# Production mode: no --reload, single worker, full performance
venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
