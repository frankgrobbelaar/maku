; A small installer that runs Maku's install hooks (hooks.nsh) around a pretend copy of a new
; engine, into a scratch folder: hooks-test.ps1 builds and runs it. Not part of Maku's installer.
; makensis /DHOOKS=<hooks.nsh> /DOUT=<exe> /DDIR=<install folder> [/DSTOP] hooks-test.nsi
Unicode true
RequestExecutionLevel user
SilentInstall silent
!include LogicLib.nsh
!include FileFunc.nsh
!include "${HOOKS}"

Name "Maku install hooks test"
OutFile "${OUT}"
InstallDir "${DIR}"

Section Install
  SetOutPath $INSTDIR
  !insertmacro NSIS_HOOK_PREINSTALL
  !ifdef STOP
    Abort "stopped on purpose"
  !endif
  CreateDirectory "$INSTDIR\engine\_internal\maku-0.3.0.dist-info"
  FileOpen $0 "$INSTDIR\engine\_internal\maku-0.3.0.dist-info\METADATA" w
  FileWrite $0 "Version: 0.3.0"
  FileClose $0
  FileOpen $0 "$INSTDIR\engine\new-engine.txt" w
  FileWrite $0 "new"
  FileClose $0
  !insertmacro NSIS_HOOK_POSTINSTALL
SectionEnd
