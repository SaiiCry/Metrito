# Watchdog permanente para mantener http://127.0.0.1:8000 siempre encendido
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

while ($true) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Iniciando servidor SIMMA en http://127.0.0.1:8000/ ..."
    & ".\.venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000 --noreload
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Proceso finalizado (código $LASTEXITCODE). Reiniciando automáticamente en 1 segundo..."
    Start-Sleep -Seconds 1
}
