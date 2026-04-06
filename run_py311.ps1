$pythonExe = Join-Path $env:USERPROFILE "anaconda3\envs\py311\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Error "Python executable not found: $pythonExe"
    exit 1
}

& $pythonExe (Join-Path $PSScriptRoot "app.py")
