param(
    [string]$KeyPath = "$env:USERPROFILE\.ssh\poe2tradehelper_proxy_ed25519",
    [string]$FirstHost = "45.9.74.103",
    [int]$FirstPort = 1080,
    [string]$SecondHost = "166.88.186.13",
    [int]$SecondPort = 1081
)

$ErrorActionPreference = "Stop"

function Get-TunnelProcess {
    param([int]$Port)
    Get-CimInstance Win32_Process -Filter "Name = 'ssh.exe'" |
        Where-Object { $_.CommandLine -match "-D\s+127\.0\.0\.1:$Port(\s|$)" }
}

function Start-Tunnel {
    param(
        [string]$HostName,
        [int]$Port
    )

    $existing = Get-TunnelProcess -Port $Port
    if ($existing) {
        return [pscustomobject]@{ Host = $HostName; Port = $Port; Status = "already-running"; Pid = $existing.ProcessId }
    }

    $args = @(
        "-i", $KeyPath,
        "-N",
        "-D", "127.0.0.1:$Port",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "root@$HostName"
    )
    $process = Start-Process -FilePath "ssh.exe" -ArgumentList $args -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 1
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -in @("127.0.0.1", "0.0.0.0", "::", "::1") }
    $status = if ($listener) { "started" } elseif ($process.HasExited) { "failed" } else { "starting" }
    [pscustomobject]@{ Host = $HostName; Port = $Port; Status = $status; Pid = $process.Id }
}

if (!(Test-Path -LiteralPath $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

$results = @(
    Start-Tunnel -HostName $FirstHost -Port $FirstPort
    Start-Tunnel -HostName $SecondHost -Port $SecondPort
)

$results | Format-Table -AutoSize
