"""The text of a file the user drops on the AI instruction, for a draft.

The reply and new-mail windows say "drop a file for context": the file's
text then goes into the draft's prompt as reference material. The windows
called /office/upload, an endpoint of the app the console came from that
GigaMail never had: the drop showed the file's name and sent nothing, and
the draft was written without it. This is that endpoint.
"""
import os
import tempfile
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from gigamail import policy
from gigamail.core import file_extractor

router = APIRouter()

# A file larger than this is not a context for one mail.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


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
