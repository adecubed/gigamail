# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Notifica desktop locale, best-effort.

Il canale "PC" della notifica di approvazione: quando il watcher (o un
tool MCP) crea una richiesta, l'umano deve VEDERLA anche se non sta
guardando ne' la chat ne' la console. Windows: toast nativa (WinRT, la
stessa famiglia gia' usata per Windows Hello); macOS: osascript; Linux:
notify-send se esiste.

SOLO NOTIFICA, mai approvazione: la toast non ha bottoni che approvano.
Approvi da console o CLI, dietro Hello — il canale che mostra non e' mai
il canale che decide.

GIGAMAIL_NOTIFY_DESKTOP=0 la spegne (default: attiva).
"""
import os
import subprocess
import sys
import threading

_APP_ID = "GigaMail"


def enabled() -> bool:
    return os.environ.get("GIGAMAIL_NOTIFY_DESKTOP", "1") not in ("0", "false", "")


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


# Misurato dal vivo (Windows 11, 2026-08-21): la chiave di registro
# HKCU\Software\Classes\AppUserModelId da sola NON basta — Windows scarta
# silenziosamente le toast finche' non esiste un collegamento nel menu
# Start (per-utente) con la proprieta' System.AppUserModel.ID. E' il
# requisito documentato per le app desktop non pacchettizzate; qui lo
# assolviamo da soli, una volta, senza installer. Il COM (IShellLink +
# IPropertyStore) lo fa un PowerShell embedded: farlo in ctypes puro
# sarebbe piu' fragile del problema che risolve.
_SHORTCUT_PS = r'''
$code = @"
using System;
using System.Runtime.InteropServices;
public static class ShortcutWithAumid {
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink { }
  [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
  interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder f, int cch, IntPtr pfd, uint fl);
    void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder s, int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder s, int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder s, int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetHotkey(out short h); void SetHotkey(short h);
    void GetShowCmd(out int c); void SetShowCmd(int c);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder s, int cch, out int i);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint r);
    void Resolve(IntPtr h, uint f);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
  }
  [StructLayout(LayoutKind.Sequential, Pack = 4)] struct PropertyKey { public Guid fmtid; public uint pid; }
  [StructLayout(LayoutKind.Explicit)] struct PropVariant {
    [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p;
  }
  [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
  interface IPropertyStore {
    void GetCount(out uint n); void GetAt(uint i, out PropertyKey k);
    void GetValue(ref PropertyKey k, out PropVariant v);
    void SetValue(ref PropertyKey k, ref PropVariant v); void Commit();
  }
  [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("0000010b-0000-0000-C000-000000000046")]
  interface IPersistFile {
    void GetClassID(out Guid g); void IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint m);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string f, [MarshalAs(UnmanagedType.Bool)] bool r);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f);
  }
  public static void Create(string lnk, string target, string aumid) {
    var link = (IShellLinkW)new ShellLink();
    link.SetPath(target);
    var store = (IPropertyStore)link;
    var key = new PropertyKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
    var pv = new PropVariant { vt = 31, p = Marshal.StringToCoTaskMemUni(aumid) };
    store.SetValue(ref key, ref pv); store.Commit();
    Marshal.FreeCoTaskMem(pv.p);
    ((IPersistFile)link).Save(lnk, true);
  }
}
"@
Add-Type -TypeDefinition $code
[ShortcutWithAumid]::Create($env:GM_LNK, $env:GM_TARGET, $env:GM_AUMID)
'''


def _win_shortcut_path() -> str:
    return os.path.join(os.environ.get("APPDATA", ""),
                        "Microsoft", "Windows", "Start Menu", "Programs",
                        f"{_APP_ID}.lnk")


def _win_register_aumid() -> None:
    """Registrazione completa dell'AppID, idempotente e best-effort:
    chiave HKCU + collegamento Start Menu con System.AppUserModel.ID —
    senza il secondo, Windows scarta le toast in silenzio."""
    try:
        import winreg
        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\AppUserModelId\{_APP_ID}")
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "GigaMail")
        winreg.CloseKey(key)
    except Exception:
        pass
    try:
        lnk = _win_shortcut_path()
        if os.path.exists(lnk):
            return
        import shutil
        target = shutil.which("gigamail") or sys.executable
        env = dict(os.environ, GM_LNK=lnk, GM_TARGET=target, GM_AUMID=_APP_ID)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", _SHORTCUT_PS],
            env=env, timeout=30, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _win_toast(title: str, body: str) -> bool:
    _win_register_aumid()
    try:
        from winrt.windows.data.xml.dom import XmlDocument  # type: ignore
        from winrt.windows.ui.notifications import (  # type: ignore
            ToastNotification, ToastNotificationManager,
        )
    except ImportError:
        return _win_toast_powershell(title, body)
    xml = (
        "<toast><visual><binding template='ToastGeneric'>"
        f"<text>{_xml_escape(title)}</text>"
        f"<text>{_xml_escape(body)}</text>"
        "</binding></visual></toast>"
    )
    doc = XmlDocument()
    doc.load_xml(xml)
    # pywinrt 3.x espone l'overload con application_id come *_with_id;
    # versioni piu' vecchie come argomento posizionale. Proviamo entrambe.
    try:
        notifier = ToastNotificationManager.create_toast_notifier_with_id(_APP_ID)
    except AttributeError:
        notifier = ToastNotificationManager.create_toast_notifier(_APP_ID)
    notifier.show(ToastNotification(doc))
    return True


def _win_toast_powershell(title: str, body: str) -> bool:
    """Fallback senza dipendenze: la stessa toast, costruita da PowerShell.
    Il testo viaggia via variabili d'ambiente, mai interpolato nel comando."""
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,"
        "ContentType=WindowsRuntime]|Out-Null;"
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$t=\"<toast><visual><binding template='ToastGeneric'><text>\""
        "+[System.Security.SecurityElement]::Escape($env:GM_TITLE)"
        "+\"</text><text>\""
        "+[System.Security.SecurityElement]::Escape($env:GM_BODY)"
        "+\"</text></binding></visual></toast>\";"
        "$x.LoadXml($t);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'GigaMail').Show((New-Object Windows.UI.Notifications.ToastNotification $x))"
    )
    env = dict(os.environ, GM_TITLE=title, GM_BODY=body)
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-Command", script],
        env=env, timeout=15, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _mac_notify(title: str, body: str) -> bool:
    def _q(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{_q(body)}" with title "{_q(title)}"'],
        timeout=15, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _linux_notify(title: str, body: str) -> bool:
    import shutil
    if not shutil.which("notify-send"):
        return False
    subprocess.run(["notify-send", title, body], timeout=15,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return True


def notify(title: str, body: str, background: bool = True) -> bool:
    """Mostra una notifica di sistema. Mai eccezioni verso il chiamante,
    mai bloccante (di default parte in un thread): l'esito della notifica
    non deve influenzare la creazione della richiesta."""
    if not enabled():
        return False

    def _run():
        try:
            if sys.platform == "win32":
                _win_toast(title, body)
            elif sys.platform == "darwin":
                _mac_notify(title, body)
            else:
                _linux_notify(title, body)
        except Exception:
            pass  # best-effort

    if background:
        # NON daemon: un processo breve (watch --once, CLI) deve poter
        # uscire DOPO che la notifica e' partita, non ucciderla a meta'.
        threading.Thread(target=_run, daemon=False).start()
        return True
    _run()
    return True
