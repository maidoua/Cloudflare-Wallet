$bundledPythonPath = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (Test-Path -LiteralPath $bundledPythonPath) {
    $pythonPath = $bundledPythonPath
} else {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike "*\Microsoft\WindowsApps\*" } |
        Select-Object -First 1
    $pythonPath = if ($pythonCommand) { $pythonCommand.Source } else { $null }
}

if (-not $pythonPath -or -not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python was not found. Install Python 3 or add python.exe to PATH."
}

& $pythonPath -B (Join-Path $PSScriptRoot "check_tags.py") @args
exit $LASTEXITCODE
