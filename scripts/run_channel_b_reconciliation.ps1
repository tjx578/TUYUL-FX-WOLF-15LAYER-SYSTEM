[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PasswordPointer = [IntPtr]::Zero

function Invoke-ChannelBReconciliationProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Python,

        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$OutputPath
    )

    Push-Location -LiteralPath $RepoRoot
    try {
        & $Python -m scripts.reconcile_channel_b |
            Out-File -LiteralPath $OutputPath -Encoding utf8
        return [int]$LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

try {
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "RECONCILIATION_PYTHON_NOT_FOUND"
    }
    if ([string]::IsNullOrEmpty($env:WOLF15_ACCOUNT_BINDING_KEY_B64URL)) {
        throw "ACCOUNT_BINDING_KEY_NOT_PRESENT"
    }
    if ([string]::IsNullOrEmpty($env:WOLF15_ACCOUNT_BINDING_KEY_ID)) {
        throw "ACCOUNT_BINDING_KEY_ID_NOT_PRESENT"
    }

    $RawVariables = railway variable list `
        --service Postgres `
        --environment production `
        --json 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "RAILWAY_VARIABLE_READ_FAILED"
    }
    $RailwayVariables = $RawVariables | ConvertFrom-Json
    if (-not $RailwayVariables.DATABASE_PUBLIC_URL) {
        throw "DATABASE_PUBLIC_URL_ABSENT"
    }
    if (-not $RailwayVariables.PGDATABASE) {
        throw "PGDATABASE_ABSENT"
    }

    $PublicEndpoint = [Uri]$RailwayVariables.DATABASE_PUBLIC_URL
    if ($PublicEndpoint.Scheme -notin @("postgres", "postgresql") -or
        -not $PublicEndpoint.Host -or
        $PublicEndpoint.Port -le 0) {
        throw "DATABASE_PUBLIC_URL_INVALID"
    }

    $AuditHost = $PublicEndpoint.Host
    $AuditPort = $PublicEndpoint.Port
    $AuditDatabase = [string]$RailwayVariables.PGDATABASE

    Remove-Variable RawVariables, RailwayVariables, PublicEndpoint -ErrorAction SilentlyContinue

    $SecureAuditPassword = Read-Host `
        "Masukkan password wolf15_auditor (input tidak terlihat)" `
        -AsSecureString
    $PasswordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
        $SecureAuditPassword
    )
    $PlainAuditPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
        $PasswordPointer
    )
    if ([string]::IsNullOrEmpty($PlainAuditPassword)) {
        throw "AUDITOR_PASSWORD_EMPTY"
    }

    $EncodedAuditPassword = [Uri]::EscapeDataString($PlainAuditPassword)
    $EncodedAuditDatabase = [Uri]::EscapeDataString($AuditDatabase)
    $env:AUDIT_DATABASE_URL = `
        "postgresql://wolf15_auditor:${EncodedAuditPassword}@${AuditHost}:${AuditPort}/${EncodedAuditDatabase}?sslmode=require"

    $AuditExitCode = Invoke-ChannelBReconciliationProcess `
        -Python $Python `
        -RepoRoot $RepoRoot `
        -OutputPath $OutputPath
    exit $AuditExitCode
}
catch {
    $KnownFailureCodes = @(
        "RECONCILIATION_PYTHON_NOT_FOUND",
        "ACCOUNT_BINDING_KEY_NOT_PRESENT",
        "ACCOUNT_BINDING_KEY_ID_NOT_PRESENT",
        "RAILWAY_VARIABLE_READ_FAILED",
        "DATABASE_PUBLIC_URL_ABSENT",
        "PGDATABASE_ABSENT",
        "DATABASE_PUBLIC_URL_INVALID",
        "AUDITOR_PASSWORD_EMPTY"
    )
    $FailureCode = if ($_.Exception.Message -in $KnownFailureCodes) {
        $_.Exception.Message
    }
    else {
        "SECURE_LAUNCHER_FAILURE"
    }
    $Failure = @{
        schema_version = "wolf15.channel-b-reconciliation.v2"
        AUDIT_DATABASE_URL = "NOT_AVAILABLE"
        DATABASE_MIRROR_STATE = "NOT_MEASURED"
        DIRECT_BROKER_STATE = "NOT_MEASURED"
        BROKER_RECONCILIATION = "NOT_EXECUTED"
        "B-B16" = "NOT_EXECUTED"
        EXECUTION_READY = $false
        PRODUCTION_READY = $false
        error_type = $FailureCode
    } | ConvertTo-Json
    $Failure | Out-File -LiteralPath $OutputPath -Encoding utf8
    exit 5
}
finally {
    Remove-Item Env:AUDIT_DATABASE_URL -ErrorAction SilentlyContinue
    if ($PasswordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PasswordPointer)
    }
    Remove-Variable `
        PlainAuditPassword,
        EncodedAuditPassword,
        EncodedAuditDatabase,
        SecureAuditPassword,
        AuditHost,
        AuditPort,
        AuditDatabase,
        PasswordPointer `
        -ErrorAction SilentlyContinue
}
