#Requires -Version 5.1
# windows_event_log.ps1 — Windows Event Log Errors
# Exit 0=ok, 1=warning, 2=critical
# Env: LOG_NAMES, LOOKBACK_MINUTES, LEVELS, PROVIDER_INCLUDE, PROVIDER_EXCLUDE, WARN_COUNT, CRIT_COUNT

$LogNames        = if ($Env:LOG_NAMES)        { $Env:LOG_NAMES }        else { 'System,Application' }
$LookbackMinutes = if ($Env:LOOKBACK_MINUTES) { [int]$Env:LOOKBACK_MINUTES } else { 30 }
$LevelsRaw       = if ($Env:LEVELS)           { $Env:LEVELS }           else { '1,2' }
$ProviderInclude = if ($Env:PROVIDER_INCLUDE) { $Env:PROVIDER_INCLUDE } else { '' }
$ProviderExclude = if ($Env:PROVIDER_EXCLUDE) { $Env:PROVIDER_EXCLUDE } else { '' }
$WarnCount       = if ($Env:WARN_COUNT)       { [int]$Env:WARN_COUNT }  else { 1 }
$CritCount       = if ($Env:CRIT_COUNT)       { [int]$Env:CRIT_COUNT }  else { 10 }

$levels    = $LevelsRaw -split ',' | ForEach-Object { [int]$_.Trim() }
$logList   = $LogNames  -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
$startTime = (Get-Date).AddMinutes(-$LookbackMinutes)

$includeProviders = @()
if ($ProviderInclude -ne '') {
    $includeProviders = $ProviderInclude -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
}

$excludeProviders = @()
if ($ProviderExclude -ne '') {
    $excludeProviders = $ProviderExclude -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
}

$allEvents  = [System.Collections.Generic.List[object]]::new()
$scanErrors = [System.Collections.Generic.List[string]]::new()

foreach ($logName in $logList) {
    try {
        $ErrorActionPreference = 'Stop'

        $filter = @{
            LogName   = $logName
            Level     = $levels
            StartTime = $startTime
        }

        $events = Get-WinEvent -FilterHashtable $filter -ErrorAction Stop

        foreach ($evt in $events) {
            # Provider include filter
            if ($includeProviders.Count -gt 0) {
                if ($includeProviders -notcontains $evt.ProviderName) {
                    continue
                }
            }

            # Provider exclude filter
            if ($excludeProviders.Count -gt 0) {
                if ($excludeProviders -contains $evt.ProviderName) {
                    continue
                }
            }

            $allEvents.Add($evt)
        }
    }
    catch [System.Exception] {
        # Get-WinEvent throws a non-terminating-style exception when no events are found
        # on PS 5.1; the message contains "No events were found"
        if ($_.Exception.Message -match 'No events were found') {
            # Not an error — just no matching events in this log
        }
        elseif ($_.Exception.Message -match 'does not exist') {
            $scanErrors.Add("Log not found: $logName")
        }
        elseif ($_ -is [System.UnauthorizedAccessException] -or $_.Exception -is [System.UnauthorizedAccessException]) {
            $scanErrors.Add("Access denied reading log: $logName")
        }
        else {
            $scanErrors.Add("Error reading log '$logName': $($_.Exception.Message)")
        }
    }
    finally {
        $ErrorActionPreference = 'Continue'
    }
}

$totalCount = $allEvents.Count

# Build top-3 most recent sample events (already ordered newest-first by Get-WinEvent)
$sampleEvents = [System.Collections.Generic.List[object]]::new()
$taken = 0
foreach ($evt in $allEvents) {
    if ($taken -ge 3) { break }

    # Truncate message to 300 chars to keep JSON compact
    $rawMsg = $evt.Message
    if ($null -eq $rawMsg) { $rawMsg = '' }
    $truncMsg = if ($rawMsg.Length -gt 300) { $rawMsg.Substring(0, 300) + '...' } else { $rawMsg }

    $sampleEvents.Add([PSCustomObject]@{
        TimeCreated  = $evt.TimeCreated.ToString('yyyy-MM-ddTHH:mm:ssZ')
        ProviderName = $evt.ProviderName
        Id           = $evt.Id
        Level        = $evt.LevelDisplayName
        LogName      = $evt.LogName
        Message      = $truncMsg
    })
    $taken++
}

# Determine exit status
if ($totalCount -ge $CritCount) {
    $status   = 'critical'
    $msg      = "CRITICAL: $totalCount event(s) in last ${LookbackMinutes}m across [$($logList -join ', ')] (threshold: $CritCount)"
    $exitCode = 2
}
elseif ($totalCount -ge $WarnCount) {
    $status   = 'warning'
    $msg      = "WARNING: $totalCount event(s) in last ${LookbackMinutes}m across [$($logList -join ', ')] (threshold: $WarnCount)"
    $exitCode = 1
}
else {
    $status   = 'ok'
    $msg      = "OK: $totalCount event(s) in last ${LookbackMinutes}m across [$($logList -join ', ')]"
    $exitCode = 0
}

$value = [ordered]@{
    total_events     = $totalCount
    lookback_minutes = $LookbackMinutes
    logs_checked     = $logList
    levels_checked   = $levels
    sample_events    = @($sampleEvents)
    scan_errors      = @($scanErrors)
}

$result = [ordered]@{
    status  = $status
    message = $msg
    value   = $value
}

Write-Output ($result | ConvertTo-Json -Compress -Depth 4)
exit $exitCode
