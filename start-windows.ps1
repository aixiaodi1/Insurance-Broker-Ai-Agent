$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "rag-backend"
$EnvFile = Join-Path $BackendDir ".env"
$ApiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "3000" }
$AdminUrl = if ($env:ADMIN_URL) { $env:ADMIN_URL } else { "http://localhost:$ApiPort/admin" }
$FrontendUrl = if ($env:FRONTEND_URL) { $env:FRONTEND_URL } else { "http://127.0.0.1:$FrontendPort/" }
$HealthUrl = if ($env:HEALTH_URL) { $env:HEALTH_URL } else { "http://localhost:$ApiPort/health" }
$LogDir = Join-Path $RootDir ".logs"

function Import-DotEnv {
    param([string]$Path)

    if (!(Test-Path $Path)) {
        throw "Missing $Path. Create it from rag-backend/.env.example first."
    }

    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (!$trimmed -or $trimmed.StartsWith("#") -or !$trimmed.Contains("=")) {
            continue
        }

        $key, $value = $trimmed.Split("=", 2)
        [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim().Trim('"').Trim("'"), "Process")
    }
}

function Convert-WslPathToWindows {
    param([string]$Path)

    if ($Path -match "^/mnt/([a-zA-Z])/(.*)$") {
        $drive = $matches[1].ToUpper()
        $rest = $matches[2] -replace "/", "\"
        return "${drive}:\$rest"
    }

    return $Path
}

function Resolve-Python {
    $candidates = @()
    if ($env:RAG_PYTHON_WINDOWS) {
        $candidates += $env:RAG_PYTHON_WINDOWS
    }
    if ($env:RAG_PYTHON) {
        $candidates += (Convert-WslPathToWindows $env:RAG_PYTHON)
    }
    $candidates += @(
        "E:\RAG\.venv\Scripts\python.exe",
        (Join-Path $BackendDir ".venv\Scripts\python.exe"),
        "python"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -eq "python") {
            $cmd = Get-Command python -ErrorAction SilentlyContinue
            if ($cmd) {
                return $cmd.Source
            }
        } elseif (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "No usable Python found. Set RAG_PYTHON_WINDOWS=E:\RAG\.venv\Scripts\python.exe in rag-backend/.env."
}

function Test-PythonModules {
    param(
        [string]$Python,
        [hashtable]$Modules
    )

    $script = @"
import importlib.util
import sys
modules = $($Modules | ConvertTo-Json -Compress)
missing = [package for package, module in modules.items() if importlib.util.find_spec(module) is None]
if missing:
    print("Missing Python packages in:", sys.executable)
    for package in missing:
        print("  -", package)
    raise SystemExit(1)
print("Using Python:", sys.executable)
"@

    $tempScript = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), ".py")
    Set-Content -Path $tempScript -Value $script -Encoding UTF8
    try {
        & $Python $tempScript
        return $LASTEXITCODE -eq 0
    } finally {
        Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-BackendDependencies {
    param([string]$Python)

    $modules = @{
        "chromadb" = "chromadb"
        "fastapi" = "fastapi"
        "httpx" = "httpx"
        "jinja2" = "jinja2"
        "pydantic-settings" = "pydantic_settings"
        "pypdf" = "pypdf"
        "python-multipart" = "multipart"
        "redis" = "redis"
        "rq" = "rq"
        "uvicorn" = "uvicorn"
    }

    if (Test-PythonModules $Python $modules) {
        return
    }

    if ($env:AUTO_INSTALL_DEPS -eq "0") {
        throw "Backend dependencies are missing. Install them with: cd rag-backend; python -m pip install -e ."
    }

    Write-Host "Installing missing backend dependencies into: $Python"
    Push-Location $BackendDir
    try {
        & $Python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e .
    } finally {
        Pop-Location
    }

    if (!(Test-PythonModules $Python $modules)) {
        throw "Backend dependency installation did not complete successfully."
    }
}

function Ensure-LocalEmbeddingDependencies {
    param([string]$Python)

    $provider = if ($env:EMBEDDING_PROVIDER) { $env:EMBEDDING_PROVIDER.ToLowerInvariant() } else { "sentence-transformers" }
    if (@("sentence-transformers", "local", "local-model") -notcontains $provider) {
        return
    }

    $modules = @{
        "sentence-transformers" = "sentence_transformers"
    }

    if (!(Test-PythonModules $Python $modules)) {
        throw "Local embedding runtime is missing from $Python. Your current RAG environment should contain sentence_transformers."
    }
}

function Start-RedisInWsl {
    $redisPort = if ($env:WINDOWS_REDIS_PORT) { $env:WINDOWS_REDIS_PORT } else { "6380" }
    $wslIpOutput = (wsl.exe bash -lc "hostname -I") -join " "
    $wslIp = ($wslIpOutput -split "\s+" | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" } | Select-Object -First 1)
    if (!$wslIp) {
        throw "Failed to resolve WSL IP address for Redis."
    }

    wsl.exe bash -lc "redis-cli -p $redisPort ping >/dev/null 2>&1 || redis-server --port $redisPort --bind 0.0.0.0 --protected-mode no --daemonize yes --dir /tmp"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start Redis in WSL."
    }

    $env:REDIS_URL = "redis://$wslIp`:$redisPort/0"
    Write-Host "Using WSL Redis at $env:REDIS_URL"
}

function Wait-ForUrl {
    param(
        [string]$Url,
        [string]$Name
    )

    Write-Host "Waiting for $Name at $Url ..."
    for ($i = 0; $i -lt 80; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
            return
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    throw "$Name did not respond at $Url. Check logs in $LogDir."
}

function Stop-ChildProcess {
    param([System.Diagnostics.Process]$Process)

    if ($Process -and !$Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ProcessOnPort {
    param([string]$Port)

    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

Import-DotEnv $EnvFile
$Python = Resolve-Python
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir "data\uploads"), (Join-Path $BackendDir "data\chroma") | Out-Null

Ensure-BackendDependencies $Python
Ensure-LocalEmbeddingDependencies $Python
Start-RedisInWsl
Stop-ProcessOnPort $ApiPort
Stop-ProcessOnPort $FrontendPort

$apiOut = Join-Path $LogDir "fastapi.out.log"
$apiErr = Join-Path $LogDir "fastapi.err.log"
$workerOut = Join-Path $LogDir "worker.out.log"
$workerErr = Join-Path $LogDir "worker.err.log"
$frontendOut = Join-Path $LogDir "frontend.out.log"
$frontendErr = Join-Path $LogDir "frontend.err.log"

Write-Host "Starting FastAPI on port $ApiPort..."
$api = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "app.main:app", "--reload", "--port", $ApiPort) -WorkingDirectory $BackendDir -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -WindowStyle Hidden -PassThru

Write-Host "Starting RQ worker for queue $env:RQ_QUEUE_NAME..."
$worker = Start-Process -FilePath $Python -ArgumentList @("-m", "rq.cli", "worker", $env:RQ_QUEUE_NAME, "--url", $env:REDIS_URL, "--worker-class", "rq.SimpleWorker") -WorkingDirectory $BackendDir -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr -WindowStyle Hidden -PassThru

Write-Host "Starting frontend on port $FrontendPort..."
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$frontend = Start-Process -FilePath $npm -ArgumentList @("run", "dev", "--", "-p", $FrontendPort, "-H", "127.0.0.1") -WorkingDirectory $RootDir -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -WindowStyle Hidden -PassThru

try {
    Start-Sleep -Seconds 2
    if ($api.HasExited) { throw "FastAPI exited during startup. Check $apiErr" }
    if ($worker.HasExited) { throw "RQ worker exited during startup. Check $workerErr" }
    if ($frontend.HasExited) { throw "Frontend exited during startup. Check $frontendErr" }

    Wait-ForUrl $HealthUrl "FastAPI"
    Wait-ForUrl $FrontendUrl "Frontend"

    Write-Host "Opening $AdminUrl"
    Start-Process $AdminUrl
    Write-Host "Opening $FrontendUrl"
    Start-Process $FrontendUrl

    Write-Host ""
    Write-Host "RAG backend and frontend are running."
    Write-Host "Logs: $LogDir"
    Write-Host "Press Ctrl+C to stop FastAPI, worker, and frontend."

    while ($true) {
        if ($api.HasExited) { throw "FastAPI stopped. Check $apiErr" }
        if ($worker.HasExited) { throw "RQ worker stopped. Check $workerErr" }
        if ($frontend.HasExited) { throw "Frontend stopped. Check $frontendErr" }
        Start-Sleep -Seconds 2
    }
} finally {
    Stop-ChildProcess $api
    Stop-ChildProcess $worker
    Stop-ChildProcess $frontend
}
