param(
    [int[]]$Ports = @(1080, 1081)
)

$ErrorActionPreference = "Stop"

$results = @()
foreach ($port in $Ports) {
    $processes = Get-CimInstance Win32_Process -Filter "Name = 'ssh.exe'" |
        Where-Object { $_.CommandLine -match "-D\s+127\.0\.0\.1:$port(\s|$)" }
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force
        $results += [pscustomobject]@{ Port = $port; Pid = $process.ProcessId; Status = "stopped" }
    }
    if (!$processes) {
        $results += [pscustomobject]@{ Port = $port; Pid = $null; Status = "not-running" }
    }
}

$results | Format-Table -AutoSize
