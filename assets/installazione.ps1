# Percorsi assoluti (necessario per WshShell)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($MyInvocation.MyCommand.Path)) }
$RootDir   = Split-Path -Parent $ScriptDir

$VbsPath   = Join-Path $ScriptDir "run_hidden.vbs"
$IconPath  = Join-Path $ScriptDir "icona.ico"
$WScript   = Join-Path $env:SystemRoot "System32\wscript.exe"

$LinkName     = "Network Analysis"
$DesktopPath  = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = "$DesktopPath\$LinkName.lnk"

$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)

$Shortcut.TargetPath       = $WScript
$Shortcut.Arguments        = "`"$VbsPath`""
$Shortcut.WorkingDirectory = $RootDir
$Shortcut.IconLocation     = $IconPath
$Shortcut.Description      = "Network Analysis - Analisi rete Enti Partner"
$Shortcut.Save()

Write-Host "Collegamento '$LinkName' creato su: $ShortcutPath" -ForegroundColor Green
Write-Host "  Target:  $WScript"
Write-Host "  Args:    $VbsPath"
Write-Host "  WorkDir: $RootDir"
