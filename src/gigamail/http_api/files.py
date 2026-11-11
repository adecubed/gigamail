"""The text of a file the user drops on the AI instruction, for a draft.

The reply and new-mail windows say "drop a file for context": the file's
text then goes into the draft's prompt as reference material. The windows
called /office/upload, an endpoint of the app the console came from that
GigaMail never had: the drop showed the file's name and sent nothing, and
the draft was written without it. This is that endpoint.

GET /files/local is the other half: the bytes of a knowledge file the
draft suggested as an attachment. The windows called it, the backend never
had it, and the 404 became an attachment with no name and a "NaN KB" size.
"""
import base64
import mimetypes
import os
import tempfile
from typing import Annotated, Iterable

from fastapi import APIRouter, File, HTTPException, UploadFile

from gigamail import policy
from gigamail.core import file_extractor

router = APIRouter()

# A file larger than this is not a context for one mail.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Nor an attachment most mail servers accept.
MAX_ATTACH_BYTES = 25 * 1024 * 1024


def _say(it: str, en: str) -> str:
    return it if policy.user_lang() == "it" else en


@router.post("/files/extract_text")
async def extract_text(file: Annotated[UploadFile, File()]):
    """{name, text, chars, type}. 413 past MAX_UPLOAD_BYTES, 422 when no
    text comes out (an image, a scanned PDF, an unknown format)."""
    name = os.path.basename(file.filename or "file")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, _say(f"{name}: file troppo grande (massimo 20 MB).",
                                      f"{name}: file too large (20 MB at most)."))
    suffix = os.path.splitext(name)[1].lower()
    fd, path = tempfile.mkstemp(prefix="gigamail-context-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        try:
            text, kind = file_extractor.extract_text(path, name)
        except Exception as e:
            raise HTTPException(422, _say(f"{name}: testo non leggibile ({e}).",
                                          f"{name}: no readable text ({e}).")) from e
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    text = text or ""
    # A format the extractor does not know is read as text: an image or an
    # archive comes out as noise, which is no context for a draft.
    if kind == "text" and (b"\x00" in data[:8192]
                           or text.count("�") > max(8, len(text) // 50)):
        raise HTTPException(422, _say(
            f"{name}: formato non supportato (usa PDF, Word, Excel, TXT, CSV o MD).",
            f"{name}: unsupported format (use PDF, Word, Excel, TXT, CSV or MD)."))
    text = text.replace("\x00", "").strip()
    if not text:
        raise HTTPException(422, _say(
            f"{name}: nessun testo da usare (un'immagine o un PDF scansionato?).",
            f"{name}: no text to use (an image, or a scanned PDF?)."))
    return {"name": name, "text": text, "chars": len(text), "type": kind}


def _knowledge_paths() -> Iterable[str]:
    """Every file or folder the user set as knowledge, on any account or
    folder identity: where suggested attachments come from."""
    from gigamail.core import accounts as core_accounts
    for acc in core_accounts.get_accounts():
        try:
            ident = core_accounts.get_identity(int(acc["id"]))
        except Exception:
            continue
        yield from ident.get("file_paths") or []
        for fold in (ident.get("folder_identities") or {}).values():
            yield from (fold or {}).get("file_paths") or []


def _is_knowledge_file(path: str) -> bool:
    """True for a configured file, or a file directly inside a configured
    folder (the folders are not scanned deeper when suggesting)."""
    target = os.path.normcase(os.path.realpath(path))
    for p in _knowledge_paths():
        p = (p or "").strip()
        if not p:
            continue
        real = os.path.normcase(os.path.realpath(p))
        if target == real or os.path.dirname(target) == real:
            return True
    return False


@router.get("/files/local")
def local_file(path: str):
    """{name, data_b64, type, size} of a knowledge file, to attach it.
    Any other path is refused: the console asks only for files it was
    offered, and the backend does not hand out the disk."""
    from gigamail.core import mail_guard
    name = os.path.basename(path or "")
    if not path or not os.path.isfile(path) or not _is_knowledge_file(path):
        raise HTTPException(404, _say(f"{name or 'file'}: non tra i file di conoscenza.",
                                      f"{name or 'file'}: not one of the knowledge files."))
    if mail_guard.is_executable_name(name):
        raise HTTPException(403, _say(f"{name}: è un programma, non si allega.",
                                      f"{name}: it is a program, it is not attached."))
    size = os.path.getsize(path)
    if size > MAX_ATTACH_BYTES:
        raise HTTPException(413, _say(f"{name}: file troppo grande (massimo 25 MB).",
                                      f"{name}: file too large (25 MB at most)."))
    with open(path, "rb") as f:
        data = f.read()
    return {"name": name,
            "data_b64": base64.b64encode(data).decode("ascii"),
            "type": mimetypes.guess_type(name)[0] or "application/octet-stream",
            "size": len(data)}
