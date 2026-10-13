# SPDX-License-Identifier: GPL-2.0-or-later

<#
.SYNOPSIS
Build and smoke-test VioletBlender on Windows x64 with Visual Studio 2022.
#>
[CmdletBinding()]
param(
    [ValidateSet('Release', 'Debug', 'RelWithDebInfo')]
    [string]$Configuration = 'Release',
    [string]$BuildDirectory,
    [string]$InstallDirectory,
    [ValidateRange(1, 64)]
    [int]$Jobs = 2,
    [ValidateSet('All', 'Prepare', 'Build', 'Test')]
    [string]$Phase = 'All',
    [string]$SourceLfsUrl = 'https://projects.blender.org/blender/blender.git/info/lfs',
    [switch]$Launch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param([string]$Command, [string[]]$CommandArguments)
    Write-Host "> $Command $($CommandArguments -join ' ')"
    & $Command @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'Run this script on Windows x64.'
}
if ($Launch -and $Phase -notin @('All', 'Test')) {
    throw '-Launch requires -Phase All or Test.'
}

$sourceDirectory = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$parentDirectory = Split-Path $sourceDirectory -Parent
if (-not $BuildDirectory) {
    $BuildDirectory = Join-Path $parentDirectory "build_violet_windows_$Configuration"
}
$BuildDirectory = [IO.Path]::GetFullPath($BuildDirectory)
if (-not $InstallDirectory) {
    $InstallDirectory = Join-Path $BuildDirectory 'install'
}
$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)

if ($Phase -ne 'Test') {
    $git = (Get-Command git -ErrorAction Stop).Source
    $cmake = (Get-Command cmake -ErrorAction Stop).Source
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (-not (Test-Path $vswhere)) {
        throw 'Install Visual Studio 2022 or Build Tools with the Desktop development with C++ workload.'
    }
    # Include Build Tools as well as the IDE; keep selection restricted to supported VS 2022.
    $vsInstall = & $vswhere -latest -products '*' -version '[17.14.14,18.0)' `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($LASTEXITCODE -ne 0 -or -not $vsInstall) {
        throw 'Visual Studio 2022 17.14.14+ with MSVC x64 tools and a Windows SDK is required.'
    }
    $vsInstall = ($vsInstall | Select-Object -First 1).Trim()
}

New-Item -ItemType Directory -Force -Path $BuildDirectory | Out-Null
$logName = "windows-$($Phase.ToLowerInvariant()).log"
if ($Phase -eq 'All') { $logName = 'windows-build.log' }
Start-Transcript -Path (Join-Path $BuildDirectory $logName) -Force | Out-Null
Push-Location $sourceDirectory
try {
    Write-Host "Phase: $Phase; source: $sourceDirectory"
    if ($Phase -in @('All', 'Prepare')) {
        Invoke-Checked $git @('lfs', 'version')
        Invoke-Checked $git @('lfs', 'install', '--local')
        Invoke-Checked $cmake @('--version')
        Write-Host "Visual Studio: $vsInstall"
        Write-Host "Source: $sourceDirectory"
        Invoke-Checked $git @('rev-parse', 'HEAD')

        # Forks of Blender often contain pointers but do not host the upstream LFS objects.
        # Scope the fallback URL to this command, and avoid downloading the large test dataset.
        Invoke-Checked $git @('-c', "lfs.url=$SourceLfsUrl", 'lfs', 'pull',
            '--include=', '--exclude=tests/**')

        # Use the gitlink recorded in this checkout, never the dependency repository's latest main.
        $librarySubmodule = 'lib/windows_x64'
        Invoke-Checked $git @('config', '--local', "submodule.$librarySubmodule.update", 'checkout')
        $savedSkipSmudge = $env:GIT_LFS_SKIP_SMUDGE
        try {
            $env:GIT_LFS_SKIP_SMUDGE = '1'
            Invoke-Checked $git @('submodule', 'update', '--init', '--depth', '1', '--progress',
                $librarySubmodule)
        }
        finally {
            $env:GIT_LFS_SKIP_SMUDGE = $savedSkipSmudge
        }
        Invoke-Checked $git @('-C', $librarySubmodule, 'lfs', 'pull', '--include=', '--exclude=')
        Invoke-Checked $git @('submodule', 'status', $librarySubmodule)
        Write-Host 'Source assets and pinned Windows libraries are ready.'
    }

    if ($Phase -in @('All', 'Build')) {
        Invoke-Checked $cmake @('-S', $sourceDirectory, '-B', $BuildDirectory,
            '-G', 'Visual Studio 17 2022', '-A', 'x64',
            "-DCMAKE_GENERATOR_INSTANCE=$vsInstall",
            "-DCMAKE_INSTALL_PREFIX=$InstallDirectory",
            '-DWITH_WINDOWS_BUNDLE_CRT=ON', '-DWITH_PYTHON_INSTALL=ON',
            '-DWITH_GPU_SHADER_CPP_COMPILATION=OFF',
            '-DWITH_CYCLES_CUDA_BINARIES=OFF', '-DWITH_CYCLES_HIP_BINARIES=OFF',
            '-DWITH_CYCLES_ONEAPI_BINARIES=OFF')
        Invoke-Checked $cmake @('--build', $BuildDirectory, '--config', $Configuration,
            '--target', 'INSTALL', '--parallel', "$Jobs")
        Write-Host "Build and install succeeded: $InstallDirectory"
    }

    if ($Phase -in @('All', 'Test')) {
        $blender = Join-Path $InstallDirectory 'blender.exe'
        if (-not (Test-Path $blender)) {
            throw "The installed executable is missing: $blender"
        }
        Invoke-Checked $blender @('--version')
        Invoke-Checked $blender @('--background', '--factory-startup', '--disable-autoexec',
            '--python-exit-code', '1', '--python',
            (Join-Path $PSScriptRoot 'violet_smoke_test.py'))
        Write-Host "Background smoke test succeeded: $blender"
        if ($Launch) {
            Start-Process -FilePath $blender -ArgumentList '--factory-startup', '--disable-autoexec'
        }
    }
}
finally {
    Pop-Location
    Stop-Transcript | Out-Null
}
