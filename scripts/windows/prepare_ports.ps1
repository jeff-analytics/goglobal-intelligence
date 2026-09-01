$ErrorActionPreference = "Stop"

# Older V5.3.8 packages keep API/UI children in restart loops. Close those
# wrapper windows first so a killed listener cannot reappear two seconds later.
try {
    $staleWrappers = @(Get-CimInstance Win32_Process | Where-Object {
        [string]$_.CommandLine -match "(?i)start_(backend|frontend)_win\.bat"
    })
    foreach ($proc in $staleWrappers) {
        Write-Host "[PORT] Closing previous GoGlobal/BorderMargin service window (PID $($proc.ProcessId))..."
        & taskkill /PID $proc.ProcessId /T /F *> $null
    }
    if ($staleWrappers.Count -gt 0) { Start-Sleep -Milliseconds 2400 }
} catch {}

function Get-ListeningPids([int]$Port) {
    try {
        return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        $rows = netstat -ano -p TCP | Select-String -Pattern (":$Port\s+.*LISTENING\s+(\d+)\s*$")
        $ids = @()
        foreach ($row in $rows) {
            if ($row.Matches.Count -gt 0) { $ids += [int]$row.Matches[0].Groups[1].Value }
        }
        return @($ids | Select-Object -Unique)
    }
}

function Get-ProcessCommand([int]$OwnerPid) {
    try { return [string](Get-CimInstance Win32_Process -Filter "ProcessId=$OwnerPid").CommandLine } catch { return "" }
}

function Test-GoGlobalListener([int]$Port, [int]$OwnerPid) {
    if ($Port -eq 8000) {
        try {
            $h = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 1
            if ($h.service -eq "GoGlobal Intelligence API" -or $h.service -eq "BorderMargin API") { return $true }
        } catch {}
    }
    if ($Port -eq 5173) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5173" -TimeoutSec 1
            if ([string]$r.Content -match "<title>(GoGlobal Intelligence|BorderMargin)</title>") { return $true }
        } catch {}
    }
    $cmd = Get-ProcessCommand $OwnerPid
    if ($cmd -match "(?i)(GoGlobal Intelligence|BorderMargin)") {
        if ($Port -eq 8000 -and $cmd -match "(?i)(uvicorn|app\.main:app)") { return $true }
        if ($Port -eq 5173 -and $cmd -match "(?i)(vite|npm)") { return $true }
    }
    return $false
}

foreach ($port in @(8000,5173)) {
    $listeners = @(Get-ListeningPids $port)
    foreach ($ownerPid in $listeners) {
        if (Test-GoGlobalListener $port $ownerPid) {
            Write-Host "[PORT] Closing previous GoGlobal/BorderMargin listener on port $port (PID $ownerPid)..."
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 350
        } else {
            $cmd = Get-ProcessCommand $ownerPid
            Write-Host "[ERROR] Port $port is already used by another application (PID $ownerPid)." -ForegroundColor Red
            if ($cmd) { Write-Host "        $cmd" }
            exit 12
        }
    }
}

Start-Sleep -Milliseconds 350
foreach ($port in @(8000,5173)) {
    if (@(Get-ListeningPids $port).Count -gt 0) {
        Write-Host "[ERROR] Port $port could not be released." -ForegroundColor Red
        exit 13
    }
}
exit 0
