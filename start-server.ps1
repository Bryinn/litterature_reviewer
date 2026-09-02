$ErrorActionPreference = 'Stop'

$port = 8765
$serverScript = Join-Path $PSScriptRoot 'server.py'

if (-not (Test-Path -LiteralPath $serverScript -PathType Leaf)) {
    throw "Could not find server.py in $PSScriptRoot"
}

Write-Host "Literature review server starting on port $port" -ForegroundColor Cyan
Write-Host "Open http://localhost:$port in your browser." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server." -ForegroundColor Yellow
Write-Host ""

& py $serverScript --port $port
