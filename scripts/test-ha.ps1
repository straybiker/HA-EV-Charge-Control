<#
.SYNOPSIS
Runs the full test suite, including the Home Assistant tests, in Docker.

.DESCRIPTION
The Home Assistant test harness needs Linux. This script builds a small
image with the pinned test dependencies (cached after the first build) and
runs pytest against the repository mounted at /src.

Every argument goes to pytest unchanged, for example:
    .\scripts\test-ha.ps1 tests/ha -x -p no:logging
#>

# No param() block on purpose: PowerShell would match pytest options such as
# -p against a script parameter name and swallow them.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$image = 'ev-charge-control-tests'

docker build -q -f "$repo/scripts/ha-tests.Dockerfile" -t $image $repo | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$cmd = @('pytest', '-q', '-p', 'no:cacheprovider') + $args
docker run --rm -v "${repo}:/src" $image @cmd
exit $LASTEXITCODE
