# Quick local development helpers (PowerShell)

Write-Host "Starting infrastructure + API + worker..." -ForegroundColor Cyan
docker compose up -d --build postgres redis minio minio-init api worker

Write-Host "`nWhen healthy:" -ForegroundColor Green
Write-Host "  API:  http://localhost:8000/health"
Write-Host "  MinIO console: http://localhost:9001 (minioadmin/minioadmin)"
Write-Host "`nIn another terminal:" -ForegroundColor Yellow
Write-Host "  cd frontend; npm run dev"
Write-Host "  open http://localhost:3000"
Write-Host "`nOffline checks:" -ForegroundColor Yellow
Write-Host "  `$env:PYTHONPATH='backend'; python scripts/offline_acceptance.py"
Write-Host "  python scripts/e2e_api_smoke.py   # needs OPENAI_API_KEY + running stack"
