# GigaMail — mail for your AI agent
# Copyright (C) 2026 Adecubed
# Licensed under the GNU AGPL v3 or later. See LICENSE.
"""Cover the fields of a scanned form before anyone else sees it.

A form filled in by hand and scanned has no text: the page is a picture.
The handwriting is hard to read, but the labels are PRINTED ("Full
name"), and printed text is found reliably, with its position. So the
handwriting is never read: each label named by the account's field rules
(core/attachment_mask) is looked for on the page, the area to its right
is painted white, and the replacement is printed on it. The area follows
the label, so a scan that is shifted or a little skewed is covered where
the field really is.

What comes out is a new PDF made of the covered pictures only: nothing
of the original page is under the white. A form where one of the labels
is not found is NOT released, because the field it names would be in
clear.

Replacements cannot depend on what was written, since it is not read:
a placeholder carries the number of the document ("FULL_NAME_12"), and
every document gets its own number, kept in a local table so that the
same file always has the same one. Two forms from the same person
cannot be told apart from two forms from different people.

How far the field goes is an estimate: from the label to the mirrored
page margin, a little taller than a printed box usually is. Writing
that spills outside of it stays visible.

Reading the printed labels needs the optional `scans` dependency
(RapidOCR, local models, nothing leaves the machine).
"""
import difflib
import hashlib
import io
import math
import os
import re
import sqlite3
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from gigamail.core import attachment_mask

RENDER_SCALE = 2.0            # 144 dpi: enough for printed labels
_LABEL_MATCH = 0.85           # how alike an OCR line and a label must be
# The covered area, in label heights: a gap after the label, and how far
# above and below its middle line. A printed box is usually two to three
# label heights tall.
_GAP = 0.5
_HALF_HEIGHT = 1.4

Quad = List[Tuple[float, float]]           # top-left, top-right, bottom-right, bottom-left
OcrItem = Tuple[Quad, str]
Ocr = Callable[[object], List[OcrItem]]    # a PIL image -> its printed lines


class Covered(NamedTuple):
    pdf: Optional[bytes]      # None when the form is not released
    replaced: List[str]       # "label -> replacement", for the user
    missing: List[str]        # labels found on no page


def available() -> bool:
    """Whether printed labels can be read on this installation."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


_engine = None


def _default_ocr(image) -> List[OcrItem]:
    global _engine
    import numpy
    from rapidocr_onnxruntime import RapidOCR
    if _engine is None:
        _engine = RapidOCR()
    result, _elapsed = _engine(numpy.array(image))
    return [([(float(x), float(y)) for x, y in quad], str(text))
            for quad, text, _score in (result or [])]


# ── geometry ─────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return " ".join(str(text).casefold().split())


def _page_slope(items: List[OcrItem]) -> float:
    """The skew of the scan: the middle slope of its long printed lines.
    One short label alone gives a slope too rough to draw along."""
    slopes = []
    for quad, _text in items:
        (x0, y0), (x1, y1) = quad[0], quad[1]
        width, height = x1 - x0, math.hypot(quad[3][0] - x0, quad[3][1] - y0)
        if width > 4 * max(1.0, height):
            slopes.append((y1 - y0) / width)
    if not slopes:
        return 0.0
    slopes.sort()
    return slopes[len(slopes) // 2]


def _find_label(items: List[OcrItem], label: str, taken: set) -> Optional[Tuple[int, Quad]]:
    """The printed line that is this label, as (index, quad of the label
    alone). A line that goes on after the label (label and value read as
    one) is cut where the label ends."""
    want = _norm(label)
    best, best_score = None, 0.0
    for i, (quad, text) in enumerate(items):
        if i in taken:
            continue
        got = _norm(text)
        if not got:
            continue
        score = difflib.SequenceMatcher(None, got[:len(want)], want).ratio()
        # "Name" must not match the head of "Names of the films".
        if got.startswith(want) and len(got) > len(want) and got[len(want)].isalnum():
            score = 0.0
        if score > best_score:
            best, best_score = (i, quad, got), score
    if not best or best_score < _LABEL_MATCH:
        return None
    i, quad, got = best
    if len(got) > len(want) + 2:
        part = len(want) / len(got)
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = quad
        quad = [(x0, y0), (x0 + (x1 - x0) * part, y0 + (y1 - y0) * part),
                (x3 + (x2 - x3) * part, y3 + (y2 - y3) * part), (x3, y3)]
    return i, quad


def _zone(label: Quad, page_width: float, slope: float) -> Tuple[Quad, float]:
    """The area to cover next to a label, and the label's height."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = label
    height = max(1.0, math.hypot(x3 - x0, y3 - y0))
    left = x1 + height * _GAP
    right = max(left + height, page_width - x0)       # the mirrored margin
    middle = (y1 + y2) / 2
    half = height * _HALF_HEIGHT

    def at(x, dy):
        return (x, middle + slope * (x - x1) + dy)
    return [at(left, -half), at(right, -half), at(right, half), at(left, half)], height


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                  # Pillow before 10.1
        return ImageFont.load_default()


def _replacement(rule: Dict[str, str], number: int, key: bytes) -> str:
    if rule["action"] == "fixed":
        return rule["value"]
    if rule["action"] == "fake_name":
        # Not read, so not the same for the same person: one per document.
        return attachment_mask._fake_name(key, f"document {number}")
    prefix = re.sub(r"[^A-Z0-9_]", "", re.sub(r"\s+", "_", rule["label"].strip().upper()))
    return f"{prefix or 'FIELD'}_{number}"


# ── covering ─────────────────────────────────────────────────────────

def cover_images(images: list, rules: List[Dict[str, str]], number: int, key: bytes,
                 ocr: Optional[Ocr] = None) -> Tuple[List[str], List[str]]:
    """Cover, in place, the fields the rules name on these page pictures.
    (["label -> replacement"], [labels found on no page])."""
    from PIL import ImageDraw
    ocr = ocr or _default_ocr
    replaced, found = [], set()
    ordered = sorted(rules, key=lambda r: len(r["label"]), reverse=True)
    for image in images:
        items = ocr(image)
        slope = _page_slope(items)
        draw = ImageDraw.Draw(image)
        taken = set()
        for rule in ordered:
            hit = _find_label(items, rule["label"], taken)
            if not hit:
                continue
            index, quad = hit
            taken.add(index)
            found.add(rule["label"])
            zone, height = _zone(quad, image.width, slope)
            text = _replacement(rule, number, key)
            draw.polygon(zone, fill=(255, 255, 255), outline=(130, 130, 130))
            draw.text((zone[0][0] + height * 0.5, (zone[0][1] + zone[3][1]) / 2),
                      text, font=_font(max(10, int(height))), fill=(20, 20, 20), anchor="lm")
            replaced.append(f"{rule['label']} -> {text}")
    missing = [r["label"] for r in rules if r["label"] not in found]
    return replaced, missing


def cover_pdf(pdf: bytes, rules: List[Dict[str, str]], number: int,
              ocr: Optional[Ocr] = None) -> Covered:
    """A scanned PDF with the rules' fields covered, as a new PDF of
    pictures. `pdf` is None in the result when a label was not found."""
    import pypdfium2
    document = pypdfium2.PdfDocument(pdf)
    try:
        images = [page.render(scale=RENDER_SCALE).to_pil().convert("RGB") for page in document]
    finally:
        document.close()
    if not images:
        return Covered(None, [], [r["label"] for r in rules])
    replaced, missing = cover_images(images, rules, number, attachment_mask._secret(), ocr=ocr)
    if missing:
        return Covered(None, replaced, missing)
    out = io.BytesIO()
    images[0].save(out, "PDF", resolution=72 * RENDER_SCALE, save_all=True,
                   append_images=images[1:])
    return Covered(out.getvalue(), replaced, [])


# ── numbers and files ────────────────────────────────────────────────

def _db():
    from gigamail.core.data_paths import data_root
    conn = sqlite3.connect(os.path.join(str(data_root()), ".scan_mask.db"))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS covered_document (
            account_id INTEGER NOT NULL,
            sha256     TEXT NOT NULL,
            number     INTEGER NOT NULL,
            PRIMARY KEY (account_id, sha256)
        )
    """)
    return conn


def number_for(account_id: int, pdf: bytes) -> int:
    """The number of this document for the account: the next free one the
    first time, the same one every time after."""
    digest = hashlib.sha256(pdf).hexdigest()
    with _db() as conn:
        row = conn.execute("SELECT number FROM covered_document WHERE account_id=? AND sha256=?",
                           (int(account_id), digest)).fetchone()
        if row:
            return int(row[0])
        top = conn.execute("SELECT COALESCE(MAX(number), 0) FROM covered_document WHERE account_id=?",
                           (int(account_id),)).fetchone()[0]
        conn.execute("INSERT INTO covered_document (account_id, sha256, number) VALUES (?,?,?)",
                     (int(account_id), digest, int(top) + 1))
        return int(top) + 1


def output_dir(account_id: int) -> str:
    from gigamail.core.data_paths import data_root
    path = os.path.join(str(data_root()), "covered_documents", f"account_{int(account_id)}")
    os.makedirs(path, exist_ok=True)
    return path


def save(account_id: int, number: int, pdf: bytes) -> str:
    """Write the covered PDF and return its path. The name is the number
    alone: the original file name can carry the sender's name."""
    path = os.path.join(output_dir(account_id), f"document-{number:04d}.pdf")
    with open(path, "wb") as f:
        f.write(pdf)
    return path
