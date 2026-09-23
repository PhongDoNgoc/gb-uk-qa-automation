param(
    [Parameter(Mandatory = $true)]
    [int]$PlanId,

    [Parameter(Mandatory = $true)]
    [int]$SuiteId,

    [string]$TargetEnvironment = "PROD",
    [string]$PythonCommand = "python",
    [string]$DotNetPath = "",
    [switch]$SkipPythonTests,
    [switch]$SkipDotNetTests,
    [switch]$Commit,
    [string]$CommitMessage = "Update generated automation tests",
    [switch]$Push
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location -Path $PSScriptRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Import-DotEnv {
    $envPath = Join-Path $PSScriptRoot ".env"
    if (-not (Test-Path $envPath)) {
        return
    }

    Get-Content $envPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }

        $parts = $line -split "=", 2
        if ($parts.Length -ne 2) {
            return
        }

        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"')
        [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

function Resolve-DotNetPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        if (-not (Test-Path $RequestedPath)) {
            throw "The supplied dotnet path does not exist: $RequestedPath"
        }
        return $RequestedPath
    }

    $dotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($dotnetCommand) {
        return $dotnetCommand.Source
    }

    $localDotNet = Join-Path $HOME ".dotnet\dotnet.exe"
    if (Test-Path $localDotNet) {
        return $localDotNet
    }

    throw "Could not find dotnet. Install .NET or pass -DotNetPath."
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if (-not $?) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

Import-DotEnv
$env:TEST_TARGET_ENV = $TargetEnvironment
$resolvedDotNet = Resolve-DotNetPath -RequestedPath $DotNetPath
$projectFile = Join-Path $PSScriptRoot "QA.Regression.Automation\QA.Regression.Automation.csproj"

Write-Step "Generating and associating Azure Test Plan automation"
Invoke-Checked -FilePath $PythonCommand -Arguments @(
    "main.py",
    "generate-scripts",
    "--plan-id", "$PlanId",
    "--suite-id", "$SuiteId",
    "--overwrite",
    "--associate",
    "--overwrite-association"
)

if (-not $SkipPythonTests) {
    Write-Step "Running Python validation tests"
    Invoke-Checked -FilePath $PythonCommand -Arguments @(
        "-m", "unittest",
        "tests.test_automation_generator",
        "tests.test_automation_association"
    )
}

if (-not $SkipDotNetTests) {
    Write-Step "Running .NET automation tests"
    Invoke-Checked -FilePath $resolvedDotNet -Arguments @(
        "test",
        $projectFile,
        "--configuration", "Release",
        "--logger", "trx"
    )
}

$statusBeforeCommit = git status --short
if ($Commit) {
    if (-not $statusBeforeCommit) {
        Write-Step "No changes to commit"
    }
    else {
        Write-Step "Creating git commit"
        git add -A
        if (-not $?) {
            throw "git add failed"
        }
        git commit -m $CommitMessage
        if (-not $?) {
            throw "git commit failed"
        }
    }
}

if ($Push) {
    Write-Step "Pushing current branch"
    git push origin HEAD
    if (-not $?) {
        throw "git push failed"
    }
}

Write-Step "Done"
Write-Host "Plan ID: $PlanId"
Write-Host "Suite ID: $SuiteId"
Write-Host "Target environment: $TargetEnvironment"
