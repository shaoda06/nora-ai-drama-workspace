# Read arguments from the launcher environment; no shell interpolation of paths.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$serviceRoot = $env:NORA_LAUNCH_ROOT
$ownerSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$taskName = "NoraWorkspaceBrowser-$ownerSid-$($env:NORA_LAUNCH_PORT)"
$python = Join-Path $serviceRoot '.venv\Scripts\pythonw.exe'
$arguments = '-B "' + (Join-Path $serviceRoot 'scripts\launcher.py') + '" serve'
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$folder = $scheduler.GetFolder('\')
$task = $null
try { $task = $folder.GetTask($taskName) }
catch {
    if ($_.Exception.HResult -ne -2147024894) { throw }
}
if ($null -ne $task) {
    $existing = $task.Definition
    $existingOwner = $existing.Principal.UserId
    if ($existingOwner -notlike 'S-1-*') {
        $existingOwner = ([System.Security.Principal.NTAccount]::new($existingOwner)).Translate(
            [System.Security.Principal.SecurityIdentifier]).Value
    }
    if ($existing.Actions.Count -ne 1 -or
        $existing.Actions.Item(1).Path -ne $python -or
        $existing.Actions.Item(1).Arguments -ne $arguments -or
        $existing.Actions.Item(1).WorkingDirectory -ne $serviceRoot -or
        $existingOwner -ne $ownerSid) {
        throw "System task $taskName belongs to another directory or account; left unchanged."
    }
}
if ($env:NORA_LAUNCH_ACTION -eq 'stop') {
    $stopped = $null -ne $task -and $task.State -eq 4
    if ($stopped) { $task.Stop(0) }
    @{ stopped = $stopped; name = $taskName } | ConvertTo-Json -Compress
    exit 0
}
if ($null -eq $task -or $task.State -ne 4) {
    $definition = $scheduler.NewTask(0)
    $definition.RegistrationInfo.Description = 'Nora workspace browser; manual start only.'
    $definition.Principal.UserId = $ownerSid
    $definition.Principal.LogonType = 3 # Current interactive user; no saved password.
    $definition.Principal.RunLevel = 0
    $definition.Settings.Enabled = $true
    $definition.Settings.AllowDemandStart = $true
    $definition.Settings.ExecutionTimeLimit = 'PT0S'
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.MultipleInstances = 2 # IgnoreNew
    $exec = $definition.Actions.Create(0)
    $exec.Path = $python
    $exec.Arguments = $arguments
    $exec.WorkingDirectory = $serviceRoot
    $task = $folder.RegisterTaskDefinition($taskName, $definition, 6, $ownerSid, $null, 3, $null)
    $null = $task.Run($null)
}
@{ name = $taskName } | ConvertTo-Json -Compress
