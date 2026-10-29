# Development only: create Payroll's database roles and database (ops/db/bootstrap.sql) with the
# passwords already in .env, so they are never typed or shown. psql asks for the password of the
# PostgreSQL superuser ("postgres").
#
#   powershell -ExecutionPolicy Bypass -File ops\db\setup_dev.ps1
#   powershell -ExecutionPolicy Bypass -File ops\db\setup_dev.ps1 -Psql "D:\pg\bin\psql.exe"

param(
    [string]$Psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe",
    [string]$Superuser = "postgres"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { throw ".env not found: copy .env.example to .env first." }

$values = @{}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Z_]+)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
}

function Get-Password([string]$name, [string]$role) {
    $url = $values[$name]
    if (-not $url -or $url -notmatch "^postgres://${role}:([^@]+)@[^/]+/(.+)$") {
        throw "$name in .env must look like postgres://${role}:PASSWORD@host:port/database"
    }
    return @([uri]::UnescapeDataString($Matches[1]), $Matches[2])
}

$owner, $database = Get-Password "DATABASE_OWNER_URL" "payroll_owner"
$rw, $null = Get-Password "DATABASE_URL" "payroll_rw"
$platform, $null = Get-Password "PLATFORM_DATABASE_URL" "payroll_platform"

& $Psql -U $Superuser -h localhost -d postgres -f (Join-Path $root "ops\db\bootstrap.sql") `
    -v dbname=$database -v owner_pw=$owner -v rw_pw=$rw -v platform_pw=$platform
if ($LASTEXITCODE -ne 0) { throw "psql failed (exit code $LASTEXITCODE)." }
Write-Host "Database '$database' and the payroll_* roles are ready."
