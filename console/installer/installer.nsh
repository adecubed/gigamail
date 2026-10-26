; installer.nsh — electron-builder NSIS hooks for GigaMail.
;
; Before the installer (an update too, silent or not) and the uninstaller
; touch a single file, the backend python.exe running from the install
; folder is ended: see stop_backend.ps1. electron-builder only closes
; GigaMail.exe itself; the backend outlives the window on purpose, and an
; update over a live backend leaves resources\python half replaced.

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
