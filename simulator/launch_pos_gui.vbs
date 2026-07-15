' Runs launch_pos_gui.bat completely hidden (no console flash) so the till
' opens the same way a real POS app would. Crashes still land in
' launch_error.log, written by the batch file, since pythonw would swallow them.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run """" & scriptDir & "\launch_pos_gui.bat""", 0, False
