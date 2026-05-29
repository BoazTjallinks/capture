#Requires -Version 5.1
# windows_cert_store.ps1 — Windows Certificate Store Expiry
# Exit 0=ok, 1=warning, 2=critical
# Env: STORE_PATHS, WARN_DAYS, CRIT_DAYS, SUBJECT_FILTER, EXCLUDE_EXPIRED

$StorePaths     = if ($Env:STORE_PATHS)     { $Env:STORE_PATHS }     else { 'Cert:\LocalMachine\My' }
$WarnDays       = if ($Env:WARN_DAYS)       { [int]$Env:WARN_DAYS }  else { 30 }
$CritDays       = if ($Env:CRIT_DAYS)       { [int]$Env:CRIT_DAYS }  else { 7 }
$SubjectFilter  = if ($Env:SUBJECT_FILTER)  { $Env:SUBJECT_FILTER }  else { '' }
$ExcludeExpired = if ($Env:EXCLUDE_EXPIRED) { $Env:EXCLUDE_EXPIRED } else { '0' }

$now   = Get-Date
$paths = $StorePaths -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }

$allCerts  = [System.Collections.Generic.List[object]]::new()
$scanErrors = [System.Collections.Generic.List[string]]::new()

foreach ($path in $paths) {
    try {
        $ErrorActionPreference = 'Stop'
        $items = Get-ChildItem -Path $path -Recurse -ErrorAction Stop
        foreach ($cert in $items) {
            # Only process X509Certificate2 objects (skip containers)
            if ($cert -isnot [System.Security.Cryptography.X509Certificates.X509Certificate2]) {
                continue
            }

            # Subject filter
            if ($SubjectFilter -ne '') {
                if ($cert.Subject -notmatch $SubjectFilter) {
                    continue
                }
            }

            $daysRemaining = ($cert.NotAfter - $now).TotalDays

            # Skip already-expired if requested
            if ($ExcludeExpired -eq '1' -and $daysRemaining -lt 0) {
                continue
            }

            $allCerts.Add([PSCustomObject]@{
                Subject        = $cert.Subject
                Thumbprint     = $cert.Thumbprint
                Store          = $path
                NotAfter       = $cert.NotAfter.ToString('yyyy-MM-ddTHH:mm:ssZ')
                DaysRemaining  = [math]::Round($daysRemaining, 2)
            })
        }
    }
    catch [System.UnauthorizedAccessException] {
        $scanErrors.Add("Access denied to store: $path")
    }
    catch {
        $scanErrors.Add("Error reading store '$path': $($_.Exception.Message)")
    }
    finally {
        $ErrorActionPreference = 'Continue'
    }
}

# Sort ascending by DaysRemaining so the soonest-to-expire is first
$sorted = $allCerts | Sort-Object DaysRemaining

# Classify
$critCerts = @($sorted | Where-Object { $_.DaysRemaining -lt $CritDays })
$warnCerts = @($sorted | Where-Object { $_.DaysRemaining -ge $CritDays -and $_.DaysRemaining -lt $WarnDays })

if ($critCerts.Count -gt 0) {
    $worst  = $critCerts[0]
    $status = 'critical'
    if ($worst.DaysRemaining -lt 0) {
        $msg = "CRITICAL: $($critCerts.Count) cert(s) already expired or expiring within ${CritDays}d — '$($worst.Subject)' expired $([math]::Abs([math]::Round($worst.DaysRemaining)))d ago"
    } else {
        $msg = "CRITICAL: $($critCerts.Count) cert(s) expiring within ${CritDays}d — '$($worst.Subject)' in $([math]::Round($worst.DaysRemaining))d"
    }
    $exitCode = 2
}
elseif ($warnCerts.Count -gt 0) {
    $worst  = $warnCerts[0]
    $status = 'warning'
    $msg    = "WARNING: $($warnCerts.Count) cert(s) expiring within ${WarnDays}d — '$($worst.Subject)' in $([math]::Round($worst.DaysRemaining))d"
    $exitCode = 1
}
else {
    $status   = 'ok'
    $totalOk  = $allCerts.Count
    $nextExpiry = if ($sorted.Count -gt 0) { $sorted[0].DaysRemaining } else { $null }
    if ($null -ne $nextExpiry) {
        $msg = "All $totalOk cert(s) OK — next expiry in $([math]::Round($nextExpiry))d"
    } else {
        $msg = 'No certificates found matching criteria'
    }
    $exitCode = 0
}

$value = [ordered]@{
    scanned_stores  = $paths
    total_certs     = $allCerts.Count
    critical_count  = $critCerts.Count
    warning_count   = $warnCerts.Count
    expiring_certs  = @($sorted | Where-Object { $_.DaysRemaining -lt $WarnDays })
    scan_errors     = @($scanErrors)
}

$result = [ordered]@{
    status  = $status
    message = $msg
    value   = $value
}

Write-Output ($result | ConvertTo-Json -Compress -Depth 4)
exit $exitCode
