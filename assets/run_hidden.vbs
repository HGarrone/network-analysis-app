Set FSO = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

' 1. Percorso cartella assets (dove si trova questo file)
ScriptPath = FSO.GetParentFolderName(WScript.ScriptFullName)

' 2. Cartella radice (un livello sopra assets)
RootPath = FSO.GetParentFolderName(ScriptPath)

' 3. Percorso del Launcher
LauncherPath = RootPath & "\LAUNCHER.bat"

' 4. Imposta cartella di lavoro sulla ROOT
WshShell.CurrentDirectory = RootPath

' 5. Avvia il Launcher in modalita' nascosta (0 = hidden, False = non aspettare)
WshShell.Run Chr(34) & LauncherPath & Chr(34), 0, False
