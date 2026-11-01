param(
    [ValidateSet("dev", "start", "check")]
    [string]$Mode = "dev"
)

$candidates = @()
if ($env:PYTHON) {
    $candidates += $env:PYTHON
}

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand -and $pythonCommand.Source -notlike "*\WindowsApps\*") {
    $candidates += $pythonCommand.Source
}

foreach ($root in @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python"),
    $env:ProgramFiles,
    "${env:ProgramFiles(x86)}",
    "C:\Python"
)) {
    if ($root -and (Test-Path $root)) {
        $candidates += Get-ChildItem $root -Directory -Filter "Python*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "python.exe" }
    }
}

$pythonPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $pythonPath) {
    throw "Python 3.11 or later was not found. Install Python and run npm run api again."
}

Push-Location $PSScriptRoot
try {
    & $pythonPath -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 or later is required."
    }

    & $pythonPath -c "import fastapi, pymongo, pydantic, jwt, pwdlib, cryptography, httpx, uvicorn"
    if ($LASTEXITCODE -ne 0) {
        Write-Output "Installing the FastAPI backend dependencies..."
        & $pythonPath -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
        if ($LASTEXITCODE -ne 0) {
            throw "Could not install the Python backend dependencies."
        }
    }

    if ($Mode -eq "check") {
        & $pythonPath -m compileall -q main.py serve.py test_main.py
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
        & $pythonPath -m unittest test_main.py
        exit $LASTEXITCODE
    }

    $port = 4000
    if ($env:PORT -and (-not [int]::TryParse($env:PORT, [ref]$port) -or $port -lt 1 -or $port -gt 65535)) {
        throw "PORT must be a valid TCP port."
    }

    $hostAddress = if ($Mode -eq "dev") { "127.0.0.1" } else { "0.0.0.0" }
    if ($env:HOST) {
        $hostAddress = $env:HOST
    }
    $uvicornArgs = @("-m", "uvicorn", "main:app", "--port", "$port", "--host", $hostAddress, "--proxy-headers")
    if ($env:FORWARDED_ALLOW_IPS) {
        $uvicornArgs += @("--forwarded-allow-ips", $env:FORWARDED_ALLOW_IPS)
    }
    if ($Mode -eq "dev") {
        $uvicornArgs += "--reload"
    }
    & $pythonPath @uvicornArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
