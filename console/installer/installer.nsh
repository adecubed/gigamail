; installer.nsh — electron-builder NSIS hooks for GigaMail.
;
; Before the installer (an update too, silent or not) and the uninstaller
; touch a single file, the backend python.exe running from the install
; folder is ended: see stop_backend.ps1. electron-builder only closes
; GigaMail.exe itself; the backend outlives the window on purpose, and an
; update over a live backend leaves resources\python half replaced.

;
; After the files are in place, resources\bin (gigamail.exe and
; gigamail-server.exe, on the bundled Python) is added to PATH, and removed
; by the uninstaller: see user_path.ps1. An MCP client that starts
; `gigamail-server` by name (the Codex and Claude Code plugins,
; `codex mcp add gigamail -- gigamail-server`) then finds this installation
; without the console having to write its path anywhere.

!macro _gigamailStopBackend
  InitPluginsDir
  File /oname=$PLUGINSDIR\stop_backend.ps1 "${PROJECT_DIR}\installer\stop_backend.ps1"
  nsExec::ExecToStack 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "$PLUGINSDIR\stop_backend.ps1" "$INSTDIR"'
  Pop $0
  Pop $1
!macroend

!macro customInit
  !insertmacro _gigamailStopBackend
!macroend

!macro customUnInit
  !insertmacro _gigamailStopBackend
!macroend

!macro _gigamailUserPath ACTION
  InitPluginsDir
  File /oname=$PLUGINSDIR\user_path.ps1 "${PROJECT_DIR}\installer\user_path.ps1"
  nsExec::ExecToStack 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "$PLUGINSDIR\user_path.ps1" ${ACTION} "$INSTDIR\resources\bin" $installMode'
  Pop $0
  Pop $1
!macroend

!macro customInstall
  !insertmacro _gigamailUserPath add
!macroend

!macro customUnInstall
  !insertmacro _gigamailUserPath remove
!macroend
