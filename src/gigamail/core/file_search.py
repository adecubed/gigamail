"""Read-only search of the user's own folders, with no knowledge of approvals.

Callers hand in words and folders; this module walks the folders, never
following links, skips what must never be searched, matches names and the
text of the files `file_extractor` reads by extension, and stops at fixed
limits, naming the limit that stopped it. Nothing is written, moved or
copied. Text read from a file never leaves `search`: `excerpt` is the only
function that returns some, and only a short single line.

Every exclusion is judged on the whole resolved path, never on the part
below a root. A hard link inside a root cannot be told from the file itself:
it is searched like any file.
"""
import os
import re
import threading
import time
import unicodedata
import zipfile
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from gigamail.core import attachments, file_extractor, mail_guard, rule_requests

MAX_RESULTS = 20
MAX_SECONDS = 15
MAX_ENTRIES = 20000
MAX_CONTENT_FILES = 300
MAX_CONTENT_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 50
MAX_SCANNED_CHARS = 200000
EXCERPT_CHARS = 240
# No ".doc": the extractor reads Word files with python-docx, which cannot
# read the old binary format. A .doc is found by name only.
CONTENT_EXTENSIONS = (".pdf", ".docx", ".xlsx", ".xls", ".txt", ".md", ".csv")
_ZIP_EXTENSIONS = (".docx", ".xlsx")

MAX_WORDS = 6
MIN_WORD_CHARS = 2
MAX_QUERY_CHARS = 100

_ATTR_HIDDEN_OR_SYSTEM = 0x2 | 0x4
_ATTR_REPARSE_POINT = 0x400
# RECALL_ON_DATA_ACCESS, RECALL_ON_OPEN, OFFLINE: opening such a file makes
# OneDrive download it.
_ATTR_ONLINE_ONLY = 0x400000 | 0x40000 | 0x1000

_COMBINING = re.compile("[̀-ͯ᪰-᫿᷀-᷿⃐-⃿︠-︯]")


# --- query -------------------------------------------------------------------

def _fold(text: str) -> str:
    """Lower case, accents removed, on the whole string."""
    return _COMBINING.sub("", unicodedata.normalize("NFKD", text.casefold()))


def clean_query(query: str) -> List[str]:
    """The words as they will be searched: lower case, accents removed.
    ValueError naming the limit that the query breaks."""
    raw = str(query or "").strip()
    if len(raw) > MAX_QUERY_CHARS:
        raise ValueError(f"query: at most {MAX_QUERY_CHARS} characters are allowed "
                         f"(got {len(raw)})")
    if any(rule_requests.bad_char(ch) for ch in raw):
        raise ValueError("query: no control characters, line breaks, bidirectional "
                         "controls or invisible format characters")
    words = _fold(raw).split()
    if not words:
        raise ValueError("query: at least one word is needed")
    if len(words) > MAX_WORDS:
        raise ValueError(f"query: at most {MAX_WORDS} words are allowed (got {len(words)})")
    for word in words:
        if len(word) < MIN_WORD_CHARS:
            raise ValueError(f"query: every word needs at least {MIN_WORD_CHARS} characters "
                             f"(got {word!r})")
    return words


# --- folders -----------------------------------------------------------------

def _candidate_roots() -> List[str]:
    home = os.path.expanduser("~")
    found = [os.path.join(home, name) for name in ("Documents", "Desktop", "Downloads")]
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(var)
        if value:
            found.append(value)
    return found


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _nested(inner: str, outer: str) -> bool:
    return inner != outer and inner.startswith(outer.rstrip(os.sep) + os.sep)


def default_roots() -> List[str]:
    """The default folders that exist and pass the check a named folder
    passes (`checked_folder`), resolved, each once, none inside another."""
    unique: Dict[str, str] = {}
    for raw in _candidate_roots():
        try:
            real = checked_folder(raw)
        except ValueError:
            continue
        unique.setdefault(_key(real), real)
    return [real for key, real in unique.items()
            if not any(_nested(key, other) for other in unique)]


def checked_folder(folder: str) -> str:
    """The resolved absolute path of a folder the user named, or ValueError
    with the reason."""
    raw = str(folder or "").strip()
    if not raw:
        raise ValueError("folder: a folder is needed")
    # Before anything touches the disk: looking at a path on another machine
    # already makes Windows sign in to it.
    if attachments.is_network_path(raw):
        raise ValueError(f"{raw} (a folder on a network path is not allowed)")
    if not os.path.isabs(raw):
        raise ValueError(f"{raw} (an absolute folder path is needed)")
    real = os.path.realpath(raw)
    if attachments.is_network_path(real):
        raise ValueError(f"{raw} (a folder on a network path is not allowed)")
    if not os.path.exists(real):
        raise ValueError(f"{raw} (this folder does not exist)")
    if not os.path.isdir(real):
        raise ValueError(f"{raw} (this is not a folder)")
    if os.path.dirname(real) == real:
        raise ValueError(f"{raw} (a whole drive or the filesystem root is not allowed)")
    if attachments.is_gigamail_data(real):
        raise ValueError(f"{raw} (GigaMail's own data is not allowed)")
    why = rule_requests.excluded_reason(real)
    if why:
        raise ValueError(why)
    # The walk judges the entries it meets; the folder itself and the ones
    # above it are judged here. The drive or filesystem root is left out: on
    # Windows a drive root carries the hidden and system attributes.
    folder_above = real
    while os.path.dirname(folder_above) != folder_above:
        if read_attributes(folder_above) & _ATTR_HIDDEN_OR_SYSTEM:
            raise ValueError(f"{raw} (a hidden or system folder is not allowed: "
                             f"{folder_above})")
        folder_above = os.path.dirname(folder_above)
    return real


def read_attributes(path: str) -> int:
    """The file attributes of a path (0 where there are none or they cannot
    be read)."""
    try:
        return getattr(os.stat(path), "st_file_attributes", 0)
    except OSError:
        return 0


def excluded(path: str, *, is_dir: bool, attrs: Optional[int] = None) -> str:
    """Why a resolved path is skipped by the walk, or "". The whole path is
    judged. `attrs` are the file attributes when the caller already has them
    (the walk does); otherwise they are read here (0 where there are none)."""
    if attachments.is_network_path(path):
        return f"{path} (a network path is not allowed)"
    why = rule_requests.excluded_reason(path)
    if why:
        return why
    if not is_dir and mail_guard.is_executable_name(os.path.basename(path)):
        return f"{path} (a program is not a document)"
    if attachments.is_gigamail_data(path):
        return f"{path} (GigaMail's own data is not allowed)"
    if attrs is None:
        attrs = read_attributes(path)
    if attrs & _ATTR_HIDDEN_OR_SYSTEM:
        return f"{path} (a hidden or system item is not allowed)"
    return ""


def is_online_only(path: str, attrs: Optional[int] = None) -> bool:
    """True for a OneDrive file that is not on the disk (Windows only):
    opening it would download it."""
    if attrs is None:
        try:
            attrs = getattr(os.stat(path), "st_file_attributes", 0)
        except OSError:
            return False
    return bool(attrs & _ATTR_ONLINE_ONLY)


def same_file(a: str, b: str) -> bool:
    """Both paths resolve to the same file."""
    def norm(p: str) -> str:
        return os.path.normcase(os.path.realpath(p))
    return norm(a) == norm(b)


# --- reading text, within bounds ---------------------------------------------

def _zip_too_big(path: str) -> bool:
    """A zip-based document that declares more than MAX_UNCOMPRESSED_BYTES
    once unpacked, or that is not a readable zip."""
    try:
        with zipfile.ZipFile(path) as z:
            return sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED_BYTES
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
        return True


def _read_text(path: str, timeout: float) -> Tuple[str, bool]:
    """(text cut at MAX_SCANNED_CHARS, timed_out). The extraction runs in a
    daemon thread: one that does not return in time is left behind and the
    file is treated as not matching."""
    if path.lower().endswith(_ZIP_EXTENSIONS) and _zip_too_big(path):
        return "", False
    box: List[str] = []

    def work() -> None:
        try:
            box.append(file_extractor.extract_text(
                path, max_pdf_pages=MAX_PDF_PAGES)[0] or "")
        except Exception:
            box.append("")

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return "", True
    return (box[0] if box else "")[:MAX_SCANNED_CHARS], False


def zip_too_big(path: str) -> bool:
    """Public name of the zip check `_read_text` applies (for `read_file`,
    which refuses such a file with a reason instead of reading nothing)."""
    return path.lower().endswith(_ZIP_EXTENSIONS) and _zip_too_big(path)


# --- the walk ----------------------------------------------------------------

def _is_link(entry: "os.DirEntry", attrs: int) -> bool:
    if entry.is_symlink():
        return True
    junction = getattr(entry, "is_junction", None)
    if junction:
        return bool(junction())
    # Python before 3.12: a junction is a reparse point that readlink resolves
    # (a OneDrive placeholder is a reparse point too, but readlink refuses it).
    if attrs & _ATTR_REPARSE_POINT:
        try:
            os.readlink(entry.path)
            return True
        except OSError:
            return False
    return False


def _iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).isoformat(timespec="seconds")


def search(words: List[str], roots: List[str], *,
           clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Walk `roots` and return {"results", "stopped_by", "visited"}. Every
    root is checked like a named folder (ValueError naming a refused one).
    The whole tree is walked for names first; the files that could match by
    content are opened afterwards, newest first, only to fill the slots left
    under MAX_RESULTS. A file matches by name when every word is in its name,
    by content when every word is in its name or in the first
    MAX_SCANNED_CHARS characters of its text. Name matches come first, newest
    first within each kind. No text is returned."""
    real_roots = [checked_folder(root) for root in roots]
    start = clock()
    stopped: List[str] = []
    names: List[Tuple[float, Dict[str, Any]]] = []
    candidates: List[Tuple[float, str, str]] = []
    visited = 0
    done = False

    def stop(name: str) -> None:
        nonlocal done
        if name not in stopped:
            stopped.append(name)
        if name in ("time", "entries"):
            done = True

    for root in real_roots:
        pending = [root]
        while pending and not done:
            folder = pending.pop()
            try:
                scanner = os.scandir(folder)
            except OSError:
                continue
            with scanner:
                for entry in scanner:
                    if clock() - start > MAX_SECONDS:
                        stop("time")
                        break
                    if visited >= MAX_ENTRIES:
                        stop("entries")
                        break
                    visited += 1
                    try:
                        st = entry.stat(follow_symlinks=False)
                        attrs = getattr(st, "st_file_attributes", 0)
                        if _is_link(entry, attrs):
                            continue
                        is_dir = entry.is_dir(follow_symlinks=False)
                        if not is_dir and not entry.is_file(follow_symlinks=False):
                            continue
                        if excluded(entry.path, is_dir=is_dir, attrs=attrs):
                            continue
                    except OSError:
                        continue
                    if is_dir:
                        if attrs & _ATTR_ONLINE_ONLY:
                            stop("online_only_folders")
                        else:
                            pending.append(entry.path)
                        continue
                    if all(w in _fold(entry.name) for w in words):
                        names.append((st.st_mtime, {
                            "path": entry.path, "name": entry.name, "size": st.st_size,
                            "modified": _iso(st.st_mtime), "match": "name",
                            "online_only": is_online_only(entry.path, attrs)}))
                    elif (entry.name.lower().endswith(CONTENT_EXTENSIONS)
                          and st.st_size <= MAX_CONTENT_BYTES
                          and not is_online_only(entry.path, attrs)):
                        candidates.append((st.st_mtime, entry.path, entry.name))

    names.sort(key=lambda t: -t[0])
    if len(names) > MAX_RESULTS:
        del names[MAX_RESULTS:]
        stop("results")
    results = [item for _, item in names]
    slots = MAX_RESULTS - len(results)

    if candidates and slots <= 0:
        stop("results")
    elif candidates:
        candidates.sort(key=lambda t: -t[0])
        opened = 0
        for mtime, path, name in candidates:
            if clock() - start > MAX_SECONDS:
                stop("time")
                break
            if opened >= MAX_CONTENT_FILES:
                stop("content_files")
                break
            opened += 1
            text, timed_out = _read_text(path, max(1.0, MAX_SECONDS - (clock() - start)))
            if timed_out:
                stop("time")
                break
            haystack = _fold(name + "\n" + text)
            if not all(w in haystack for w in words):
                continue
            if slots <= 0:
                stop("results")
                break
            slots -= 1
            try:
                st = os.stat(path)
            except OSError:
                continue
            results.append({"path": path, "name": name, "size": st.st_size,
                            "modified": _iso(mtime), "match": "content",
                            "online_only": False})
    return {"results": results, "stopped_by": stopped, "visited": visited}


# --- excerpt -----------------------------------------------------------------

def excerpt(path: str, words: List[str]) -> str:
    """Up to EXCERPT_CHARS characters of the file's text around the first
    word found, on one line. "" for a file that is not searched by content,
    is online-only, is too big, cannot be read in time, or does not hold the
    word. Only the first MAX_SCANNED_CHARS characters are looked at, as in
    `search`."""
    if not path.lower().endswith(CONTENT_EXTENSIONS):
        return ""
    try:
        if os.path.getsize(path) > MAX_CONTENT_BYTES:
            return ""
    except OSError:
        return ""
    if is_online_only(path):
        return ""
    text, timed_out = _read_text(path, MAX_SECONDS)
    if timed_out or not text:
        return ""
    return excerpt_of(text, words)


def excerpt_of(text: str, words: List[str]) -> str:
    """The excerpt `excerpt` returns, from text already read (for callers
    that read the file under their own bounds)."""
    text = (text or "")[:MAX_SCANNED_CHARS]
    lines = []
    offset = 0
    for line in text.splitlines(keepends=True):
        lines.append((offset, line, _fold(line)))
        offset += len(line)
    for word in words:
        for offset, line, folded in lines:
            at = folded.find(word)
            if at < 0:
                continue
            if len(folded) == len(line):
                inside = at
            else:
                # Folding changed the length: find the original character
                # that starts the match, on this one line.
                origin: List[int] = []
                for i, ch in enumerate(line):
                    origin.extend([i] * len(_fold(ch)))
                inside = origin[at] if at < len(origin) else 0
            mid = offset + inside
            begin = max(0, mid - EXCERPT_CHARS // 2)
            piece = " ".join(text[begin:begin + EXCERPT_CHARS].split())
            return piece[:EXCERPT_CHARS]
    return ""
