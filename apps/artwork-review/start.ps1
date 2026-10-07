param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$appDirectory = $PSScriptRoot
$workspaceDirectory = [System.IO.Path]::GetFullPath((Join-Path $appDirectory '..\..')).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
$pythonPath = Join-Path $workspaceDirectory '.venv\Scripts\python.exe'
$dataDirectory = Join-Path $appDirectory '.local'
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$mutexName = 'Local\ArcoReview-' + [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($appDirectory))).Substring(0, 20)
$launchMutex = [System.Threading.Mutex]::new($false, $mutexName)
$hasLock = $false
try {
    $hasLock = $launchMutex.WaitOne(30000)
    if (-not $hasLock) { throw '另一启动进程正在准备服务，请稍后重试。' }
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "找不到工作区 Python：$pythonPath。请先创建工作区 .venv。"
    }
    $instancePath = Join-Path $dataDirectory 'instance.json'
    $versionStream = [System.IO.MemoryStream]::new()
    foreach ($versionFile in @('server.py', 'core.py', 'static\app.js', 'static\style.css', 'static\index.html')) {
        $versionBytes = [System.IO.File]::ReadAllBytes((Join-Path $appDirectory $versionFile))
        $versionStream.Write($versionBytes, 0, $versionBytes.Length)
    }
    $currentVersion = [Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($versionStream.ToArray())).ToLowerInvariant()
    $versionStream.Dispose()
    $serviceUrl = $null
    if (Test-Path -LiteralPath $instancePath) {
        try {
            $instance = Get-Content -LiteralPath $instancePath -Raw | ConvertFrom-Json
            if ($instance.url -match '^http://127\.0\.0\.1:\d+$') {
                $health = Invoke-RestMethod -Uri ($instance.url + '/health') -TimeoutSec 2
                if ($health.app -eq 'arco-artwork-review' -and $health.root -eq $workspaceDirectory) {
                    if ($health.code_version -eq $currentVersion) {
                        $serviceUrl = $instance.url
                    } else {
                        # Stop only this app through its authenticated endpoint, without killing arbitrary PIDs.
                        try {
                            # Archive variants may include an empty ID; PowerShell needs a hashtable for that JSON.
                            $meta = (Invoke-WebRequest -Uri ($instance.url + '/api/bootstrap') -TimeoutSec 3).Content | ConvertFrom-Json -AsHashtable
                            Invoke-RestMethod -Method Post -Uri ($instance.url + '/api/shutdown') -Headers @{ 'X-Arco-Token' = $meta.token } -ContentType 'application/json' -Body '{}' -TimeoutSec 3 | Out-Null
                            for ($stopAttempt = 0; $stopAttempt -lt 20; $stopAttempt++) {
                                Start-Sleep -Milliseconds 250
                                try { Invoke-WebRequest -Uri ($instance.url + '/health') -TimeoutSec 1 | Out-Null }
                                catch { break }
                            }
                        } catch { }
                    }
                }
            }
        } catch { }
    }
    if (-not $serviceUrl) {
        & $pythonPath -c 'from PIL import Image' 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host '首次启动：安装缩略图依赖 Pillow…'
            & $pythonPath -m pip install --proxy 'http://127.0.0.1:7897' -r (Join-Path $appDirectory 'requirements.txt')
            if ($LASTEXITCODE -ne 0) { throw 'Pillow 安装失败，请查看上面的网络或安装错误。' }
        }
        $env:PYTHONIOENCODING = 'utf-8'
        $launchArguments = '"' + (Join-Path $appDirectory 'server.py') + '" --root "' + $workspaceDirectory + '" --data-dir "' + $dataDirectory + '"'
        $process = Start-Process -FilePath $pythonPath -ArgumentList $launchArguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataDirectory 'service.log') -RedirectStandardError (Join-Path $dataDirectory 'service-error.log')
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            Start-Sleep -Milliseconds 250
            if ($process.HasExited) { throw "服务启动失败，请查看 $dataDirectory\service-error.log" }
            try {
                $instance = Get-Content -LiteralPath $instancePath -Raw | ConvertFrom-Json
                # Windows venv's python.exe can launch a child interpreter with a different PID.
                if ($instance.url -notmatch '^http://127\.0\.0\.1:\d+$') { continue }
                $health = Invoke-RestMethod -Uri ($instance.url + '/health') -TimeoutSec 1
                if ($health.app -eq 'arco-artwork-review' -and $health.root -eq $workspaceDirectory -and $health.code_version -eq $currentVersion) {
                    $serviceUrl = $instance.url
                    break
                }
            } catch { }
        }
        if (-not $serviceUrl) { throw "服务未能就绪，请查看 $dataDirectory 中的日志。" }
    }
    if (-not $NoBrowser) { Start-Process ($serviceUrl + '/#quick') }
    Write-Output $serviceUrl
} finally {
    if ($hasLock) { $launchMutex.ReleaseMutex() }
    $launchMutex.Dispose()
}
