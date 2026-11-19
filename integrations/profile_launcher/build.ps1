param(
    [string] $OutputDir = (Join-Path $PSScriptRoot '..\..\build\profile-launcher')
)

$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw '.NET Framework C# compiler was not found.'
}
$output = [IO.Path]::GetFullPath($OutputDir)
[IO.Directory]::CreateDirectory($output) | Out-Null
$executable = Join-Path $output 'PBZRandomizer.exe'
$sources = @('Launcher.cs', 'ProfileStore.cs', 'SteamGame.cs', 'PendingLaunch.cs') | ForEach-Object { Join-Path $PSScriptRoot $_ }
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 "/out:$executable" /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Runtime.Serialization.dll $sources
if ($LASTEXITCODE -ne 0) { throw "C# compilation failed with exit code $LASTEXITCODE." }
Write-Output $executable
