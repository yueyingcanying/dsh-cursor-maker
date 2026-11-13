param(
    [Parameter(Mandatory = $true)][string]$Spec
)

# dsh-cursor-maker / registry.ps1
#
# One JSON command in, one JSON result out. Everything travels through files
# because a Chinese %LOCALAPPDATA% path turns into mojibake the moment it
# crosses a console codepage; a UTF-8 file does not care.

$ErrorActionPreference = 'Stop'

$cmd = Get-Content -LiteralPath $Spec -Raw -Encoding UTF8 | ConvertFrom-Json
$resultPath = [string]$cmd.result

$ROLES = @('Arrow', 'Help', 'AppStarting', 'Wait', 'Crosshair', 'IBeam', 'NWPen', 'No',
    'SizeNS', 'SizeWE', 'SizeNWSE', 'SizeNESW', 'SizeAll', 'UpArrow', 'Hand', 'Pin')
$KEY = 'Control Panel\Cursors'

function Open-Cursors([bool]$write) {
    $sub = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($KEY, $write)
    if ($null -eq $sub) { throw "cursor key is missing from HKCU" }
    return $sub
}

function Read-State {
    $k = Open-Cursors $false
    try {
        $map = [ordered]@{}
        foreach ($role in $ROLES) { $map[$role] = [string]$k.GetValue($role, '') }
        return [ordered]@{ scheme = [string]$k.GetValue('', ''); values = $map }
    }
    finally { $k.Close() }
}

function Write-Scheme([string]$name, $map) {
    $k = Open-Cursors $true
    try {
        foreach ($role in $ROLES) {
            $value = [string]$map.$role
            if ([string]::IsNullOrEmpty($value)) { $k.DeleteValue($role, $false) }
            else { $k.SetValue($role, $value, [Microsoft.Win32.RegistryValueKind]::ExpandString) }
        }
        $k.SetValue('', $name, [Microsoft.Win32.RegistryValueKind]::String)
        if (-not [string]::IsNullOrEmpty($name)) {
            $schemes = $k.CreateSubKey('Schemes')
            try {
                $joined = ($ROLES | ForEach-Object { [string]$map.$_ }) -join ','
                $schemes.SetValue($name, $joined, [Microsoft.Win32.RegistryValueKind]::ExpandString)
            }
            finally { $schemes.Close() }
        }
    }
    finally { $k.Close() }
}

function Publish-Cursor {
    if (-not ('CursorMaker.Win' -as [type])) {
        Add-Type -Namespace CursorMaker -Name Win -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true)]
public static extern bool SystemParametersInfo(uint action, uint param, System.IntPtr data, uint flags);
'@
    }
    [CursorMaker.Win]::SystemParametersInfo(0x0057, 0, [System.IntPtr]::Zero, 3) | Out-Null
}

function Stock-Aero {
    $root = '%SystemRoot%\cursors'
    return [ordered]@{
        scheme = 'Windows Aero'
        values = [ordered]@{
            Arrow       = "$root\aero_arrow.cur"
            Help        = "$root\aero_helpsel.cur"
            AppStarting = "$root\aero_working.ani"
            Wait        = "$root\aero_busy.ani"
            Crosshair   = ''
            IBeam       = ''
            NWPen       = "$root\aero_pen.cur"
            No          = "$root\aero_unavail.cur"
            SizeNS      = "$root\aero_ns.cur"
            SizeWE      = "$root\aero_ew.cur"
            SizeNWSE    = "$root\aero_nwse.cur"
            SizeNESW    = "$root\aero_nesw.cur"
            SizeAll     = "$root\aero_move.cur"
            UpArrow     = "$root\aero_up.cur"
            Hand        = "$root\aero_link.cur"
            Pin         = "$root\aero_pin.cur"
        }
    }
}

$result = [ordered]@{ ok = $false }

try {
    switch ([string]$cmd.action) {
        'status' {
            $state = Read-State
            $result = [ordered]@{
                ok     = $true
                scheme = $state.scheme
                values = $state.values
                backup = [bool]($cmd.backup -and (Test-Path -LiteralPath ([string]$cmd.backup)))
            }
        }
        'apply' {
            $before = Read-State
            if ($cmd.backup -and -not $before.scheme.StartsWith('DSH Cursor')) {
                $before | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath ([string]$cmd.backup) -Encoding UTF8
            }
            Write-Scheme ([string]$cmd.name) $cmd.values
            Publish-Cursor
            $after = Read-State
            $result = [ordered]@{
                ok      = $true
                scheme  = $after.scheme
                values  = $after.values
                applied = $true
            }
        }
        'restore' {
            $target = $null
            if ($cmd.backup -and (Test-Path -LiteralPath ([string]$cmd.backup))) {
                $target = Get-Content -LiteralPath ([string]$cmd.backup) -Raw -Encoding UTF8 | ConvertFrom-Json
            }
            if ($null -eq $target -or [string]::IsNullOrEmpty([string]$target.scheme)) {
                $target = Stock-Aero
            }
            $name = [string]$target.scheme
            if ($name.StartsWith('DSH Cursor')) { $name = 'Windows Aero'; $target = Stock-Aero }
            Write-Scheme $name $target.values
            Publish-Cursor
            $after = Read-State
            $result = [ordered]@{ ok = $true; scheme = $after.scheme; values = $after.values; restored = $true }
        }
        default { throw "unknown action: $($cmd.action)" }
    }
}
catch {
    $result = [ordered]@{ ok = $false; error = [string]$_.Exception.Message }
}

$json = $result | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($resultPath, $json, (New-Object System.Text.UTF8Encoding($false)))