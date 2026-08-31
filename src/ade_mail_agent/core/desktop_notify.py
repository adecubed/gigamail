# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Notifica desktop locale, best-effort.

Il canale "PC" della notifica di approvazione: quando il watcher (o un
tool MCP) crea una richiesta, l'umano deve VEDERLA anche se non sta
guardando ne' la chat ne' la console. Windows: toast nativa (WinRT, la
stessa famiglia gia' usata per Windows Hello); macOS: osascript; Linux:
notify-send se esiste.

La toast NON approva mai da sola: i suoi bottoni (Approva/Rifiuta) aprono
un URL gigamail:// che lancia la CLI, e la CLI alza Windows Hello. Il
canale che mostra apre la porta; solo l'umano la passa.

GIGAMAIL_NOTIFY_DESKTOP=0 la spegne (default: attiva).
"""
import os
import subprocess
import sys
import threading
from typing import List, Optional, Tuple

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


# Click sulla toast → approvazione. La toast puo' solo APRIRE un URL
# (activationType="protocol"): lo schema gigamail:// lancia la CLI —
# `gigamail open-url gigamail://approve/<id>` → `approvals approve` →
# prompt Hello. La toast non approva mai da sola: apre la porta, l'umano
# la passa.
#
# Misurato dal vivo (Windows 11, 2026-08-22): la registrazione PER-UTENTE
# (HKCU\Software\Classes) basta alla shell (Start-Process gigamail://...
# apre la CLI) ma NON ai bottoni delle toast, che risolvono lo schema solo
# dalle registrazioni DI MACCHINA (HKLM). Nemmeno Capabilities +
# RegisteredApplications per-utente bastano (provato). Quindi:
#   - `gigamail desktop-setup` scrive HKLM una volta, con prompt UAC
#     (register_protocol_machine);
#   - finche' non e' fatto, la toast esce SENZA bottoni (il testo dice
#     comunque come approvare): meglio di un dialogo "Ottieni un'app".
PROTOCOL = "gigamail"


_PROTOCOL_ARGS = '-m ade_mail_agent.cli open-url "%1"'


def protocol_command() -> str:
    return f'"{sys.executable}" {_PROTOCOL_ARGS}'


def protocol_registered() -> bool:
    """True se HKLM lancia la CLI GigaMail sullo schema gigamail://.

    Il confronto NON e' con sys.executable. Che i bottoni funzionino
    dipende dal comando REGISTRATO — un python che esiste e che sa aprire
    `ade_mail_agent.cli open-url` — non dal fatto che sia lo stesso
    interprete che in questo momento sta costruendo la toast. Con
    l'uguaglianza esatta bastava un secondo interprete sulla macchina (il
    python di sistema accanto a quello del venv) perche' la toast uscisse
    muta, in silenzio e senza che niente lo spiegasse: il caso piu'
    frequente, non quello raro.

    Resta stretto dove serve: gli argomenti devono essere esattamente i
    nostri e l'eseguibile deve esistere davvero, cosi' una registrazione
    di qualcun altro — o rimasta indietro rispetto a un venv cancellato —
    non ci fa promettere bottoni che poi darebbero "Ottieni un'app"."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           rf"Software\Classes\{PROTOCOL}\shell\open\command")
        val, _ = winreg.QueryValueEx(k, None)
        winreg.CloseKey(k)
    except Exception:
        return False
    return registered_command_ok(str(val))


def registered_command_ok(val: str) -> bool:
    """Il comando letto da HKLM e' il nostro e puo' partire? Pura, cosi'
    il caso "secondo interprete" resta coperto da un test invece che da un
    registro di Windows."""
    val = (val or "").strip()
    if not val.lower().endswith(_PROTOCOL_ARGS.lower()):
        return False
    exe = val[: -len(_PROTOCOL_ARGS)].strip().strip('"')
    return bool(exe) and os.path.exists(exe)


def register_protocol_machine() -> bool:
    """Scrive HKLM\Software\Classes\gigamail con un PowerShell elevato
    (prompt UAC: e' l'utente a dire si'). Ritorna True se dopo la
    registrazione risulta corretta. Idempotente."""
    if sys.platform != "win32":
        return False
    if protocol_registered():
        return True
    cmd = protocol_command().replace("'", "''")
    base = "HKLM:\\Software\\Classes\\" + PROTOCOL
    sub = base + "\\shell\\open\\command"
    script = "\n".join([
        f"$cmd = '{cmd}'",
        f"New-Item -Path '{base}' -Force | Out-Null",
        f"Set-ItemProperty '{base}' -Name '(default)' -Value 'URL:GigaMail'",
        f"Set-ItemProperty '{base}' -Name 'URL Protocol' -Value ''",
        f"New-Item -Path '{sub}' -Force | Out-Null",
        f"Set-ItemProperty '{sub}' -Name '(default)' -Value $cmd",
    ])
    path = ""
    try:
        import tempfile
        fd, path = tempfile.mkstemp(prefix="gigamail-protocol-", suffix=".ps1")
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(script)
        # Lo script viaggia su file: niente quoting annidato; -Verb RunAs
        # apre il prompt UAC, -Wait aspetta che l'utente risponda.
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Start-Process powershell -Verb RunAs -Wait -ArgumentList "
             f"'-NoProfile','-ExecutionPolicy','Bypass','-File','{path}'"],
            timeout=300, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
    return protocol_registered()


def _win_register_protocol() -> None:
    """Registrazione per-utente (HKCU): serve a ShellExecute e non guasta;
    per le toast conta register_protocol_machine()."""
    try:
        import winreg
        base = rf"Software\Classes\{PROTOCOL}"
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, base)
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "URL:GigaMail")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        winreg.CloseKey(k)
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command")
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, protocol_command())
        winreg.CloseKey(k)
    except Exception:
        pass


def actions_supported() -> bool:
    """Bottoni cliccabili sulla toast: solo Windows con lo schema
    registrato a livello macchina (gigamail desktop-setup)."""
    return sys.platform == "win32" and protocol_registered()


def build_toast_xml(title: str, body: str,
                    actions: Optional[List[Tuple[str, str]]] = None) -> str:
    """XML della toast. `actions` = [(etichetta, url gigamail://...)]:
    diventano bottoni; il primo e' anche il click sul corpo."""
    xml = "<toast"
    if actions:
        xml += f" activationType='protocol' launch='{_xml_escape(actions[0][1])}'"
        # scenario='reminder': la toast RESTA a schermo finche' l'umano
        # non decide, invece di sparire dopo pochi secondi. Windows non
        # espone una durata arbitraria per il popup (duration='long'
        # arriva a ~25s): per un'approvazione che scade in 15 minuti
        # l'unica cosa sensata e' che non se ne vada da sola. Richiede
        # almeno un bottone, e qui ce ne sono quattro.
        xml += " scenario='reminder'"
    else:
        xml += " duration='long'"
    xml += ("><visual><binding template='ToastGeneric'>"
            f"<text>{_xml_escape(title)}</text>"
            f"<text>{_xml_escape(body)}</text>"
            "</binding></visual>")
    if actions:
        xml += "<actions>"
        for label, url in actions[:5]:
            xml += (f"<action content='{_xml_escape(label)}' "
                    f"activationType='protocol' arguments='{_xml_escape(url)}'/>")
        xml += "</actions>"
    xml += "</toast>"
    return xml


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


def _toast_tag(actions: Optional[List[Tuple[str, str]]]) -> str:
    """Identita' della toast: la request_id che i bottoni aprono.

    Serve a due cose opposte e ugualmente necessarie. Senza tag,
    Windows accorpa le notifiche della stessa app e cinque
    approvazioni diverse finiscono una sopra l'altra: ne vedi una e le
    altre quattro spariscono. Con il tag ognuna e' distinta e restano
    tutte. E rilanciare la MEDESIMA richiesta sostituisce la sua
    toast invece di aggiungerne una copia."""
    import re
    for _, url in actions or []:
        # largo di proposito: un id che non combacia con la regex
        # farebbe tornare il tag vuoto, cioe' di nuovo le toast
        # accorpate, e in silenzio.
        m = re.search(r"(req_[0-9A-Za-z]+)", url)
        if m:
            return m.group(1)[:64]
    return ""


def _win_toast(title: str, body: str,
               actions: Optional[List[Tuple[str, str]]] = None,
               expires_in: Optional[int] = None) -> bool:
    _win_register_aumid()
    if actions:
        _win_register_protocol()
        if not protocol_registered():
            actions = None  # senza HKLM il bottone darebbe "Ottieni un'app"
    try:
        from winrt.windows.data.xml.dom import XmlDocument  # type: ignore
        from winrt.windows.ui.notifications import (  # type: ignore
            ToastNotification, ToastNotificationManager,
        )
    except ImportError:
        return _win_toast_powershell(title, body)
    xml = build_toast_xml(title, body, actions)
    doc = XmlDocument()
    doc.load_xml(xml)
    # pywinrt 3.x espone l'overload con application_id come *_with_id;
    # versioni piu' vecchie come argomento posizionale. Proviamo entrambe.
    try:
        notifier = ToastNotificationManager.create_toast_notifier_with_id(_APP_ID)
    except AttributeError:
        notifier = ToastNotificationManager.create_toast_notifier(_APP_ID)
    notifica = ToastNotification(doc)
    tag = _toast_tag(actions)
    if tag:
        try:
            notifica.tag = tag
            notifica.group = "approvals"
        except Exception:
            pass  # best-effort: meglio una toast accorpata che nessuna
    if expires_in:
        # Quanto resta nel centro notifiche: la richiesta scade, e una
        # toast che sopravvive alla scadenza invita a premere Approva
        # su qualcosa che non e' piu' approvabile.
        try:
            import datetime as _dt
            notifica.expiration_time = (_dt.datetime.now(_dt.timezone.utc)
                                        + _dt.timedelta(seconds=expires_in))
        except Exception:
            pass
    notifier.show(notifica)
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


def notify(title: str, body: str, background: bool = True,
           actions: Optional[List[Tuple[str, str]]] = None,
           expires_in: Optional[int] = None) -> bool:
    """Mostra una notifica di sistema. Mai eccezioni verso il chiamante,
    mai bloccante (di default parte in un thread): l'esito della notifica
    non deve influenzare la creazione della richiesta."""
    if not enabled():
        return False

    def _run():
        try:
            if sys.platform == "win32":
                _win_toast(title, body, actions, expires_in)
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
