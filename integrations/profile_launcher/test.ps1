$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
$fixture = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ("..\..\.work\launcher-test-" + [guid]::NewGuid().ToString('N'))))
[IO.Directory]::CreateDirectory($fixture) | Out-Null
$program = Join-Path $fixture 'FixtureTests.exe'
$sources = @('FixtureTests.cs', 'ProfileStore.cs', 'SteamGame.cs', 'PendingLaunch.cs') | ForEach-Object { Join-Path $PSScriptRoot $_ }
& $compiler /nologo /target:exe /codepage:65001 "/out:$program" /reference:System.Runtime.Serialization.dll $sources
if ($LASTEXITCODE -ne 0) { throw 'Fixture compilation failed.' }
$stdout = Join-Path $fixture 'stdout.txt'
$stderr = Join-Path $fixture 'stderr.txt'
$test = Start-Process -FilePath $program -ArgumentList ('"' + $fixture + '"') -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
try {
    if (-not $test.WaitForExit(30000)) {
        if (-not $test.HasExited) {
            $test.Kill()
            [void]$test.WaitForExit(3000)
        }
        throw 'Launcher fixtures did not exit within 30 seconds.'
    }
    Get-Content -LiteralPath $stdout
    Get-Content -LiteralPath $stderr
    if ($test.ExitCode -ne 0) { throw "Launcher fixtures failed with exit code $($test.ExitCode)." }
}
finally {
    $test.Dispose()
}
