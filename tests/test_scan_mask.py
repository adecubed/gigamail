"""Scanned forms: the fields next to printed labels are covered, unread.

The pictures are drawn here and the printed lines are handed in by a
stand-in for the OCR, which knows where they were drawn: the tests check
what is covered, not how well a model reads. One test at the bottom runs
the real OCR and is skipped where it is not installed.
"""
import io

import pytest
from PIL import Image, ImageDraw

from gigamail import server
from gigamail.core import attachment_mask, scan_mask

W, H = 1200, 900
NAME_BOX = (420, 200, 1080, 280)       # where the voter wrote their name
VOTE_BOX = (420, 500, 1080, 580)       # where they wrote their vote
# The printed lines of the form, as the OCR would give them.
LINES = [
    ([(100, 80), (700, 80), (700, 120), (100, 120)], "Test award 2026 - Ballot"),
    ([(100, 225), (300, 225), (300, 255), (100, 255)], "Full name"),
    ([(100, 525), (290, 525), (290, 555), (100, 555)], "Best film"),
]


def ballot() -> Image.Image:
    """A form with 'handwriting' (dark scribbles) in the two boxes."""
    img = Image.new("RGB", (W, H), (250, 250, 250))
    d = ImageDraw.Draw(img)
    for box in (NAME_BOX, VOTE_BOX):
        d.rectangle(box, outline=(60, 60, 60), width=2)
        for x in range(box[0] + 30, box[0] + 400, 25):
            d.line((x, box[1] + 20, x + 12, box[3] - 20), fill=(30, 30, 30), width=4)
    return img


def as_pdf(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PDF", resolution=72 * scan_mask.RENDER_SCALE)
    return out.getvalue()


def fake_ocr(image):
    # The PDF round trip keeps the size: the lines are where they were drawn.
    assert abs(image.width - W) <= 2
    return LINES


def ink(img: Image.Image, box) -> int:
    """Dark pixels well inside a box: what is left of the handwriting."""
    inner = img.crop((box[0] + 20, box[1] + 15, box[0] + 420, box[3] - 15)).convert("L")
    return sum(1 for p in inner.tobytes() if p < 100)


def rule(label, action="placeholder", value=""):
    return {"label": label, "action": action, "value": value}


@pytest.fixture
def settings(monkeypatch, tmp_path):
    store = {}
    monkeypatch.setattr(attachment_mask.accounts, "get_setting",
                        lambda key, default="": store.get(key, default))
    monkeypatch.setattr(attachment_mask.accounts, "set_setting",
                        lambda key, value: store.__setitem__(key, str(value)))
    monkeypatch.setattr(attachment_mask.ade_masker, "get_user_masks", lambda aid: [])
    monkeypatch.setenv("GIGAMAIL_DATA_DIR", str(tmp_path))
    return store


# ── covering ─────────────────────────────────────────────────────────

def test_the_field_next_to_its_label_is_covered_and_the_rest_stays(settings):
    img = ballot()
    assert ink(img, NAME_BOX) > 500 and ink(img, VOTE_BOX) > 500
    replaced, missing = scan_mask.cover_images([img], [rule("Full name")], 7, b"k", ocr=fake_ocr)
    assert missing == [] and replaced == ["Full name -> FULL_NAME_7"]
    # Past the replacement's own letters, where the name was is white.
    region = img.crop((NAME_BOX[0] + 220, NAME_BOX[1] + 5, NAME_BOX[2] - 20, NAME_BOX[3] - 5))
    assert min(region.convert("L").tobytes()) > 200     # past the text: all white
    assert ink(img, VOTE_BOX) > 500


def test_a_form_missing_a_label_is_not_released(settings):
    covered = scan_mask.cover_pdf(as_pdf(ballot()), [rule("Full name"), rule("Tax code")],
                                  1, ocr=fake_ocr)
    assert covered.pdf is None and covered.missing == ["Tax code"]


def test_the_covered_pdf_holds_pictures_only(settings):
    import pypdfium2
    covered = scan_mask.cover_pdf(as_pdf(ballot()), [rule("Full name")], 3, ocr=fake_ocr)
    assert covered.missing == [] and covered.pdf.startswith(b"%PDF")
    doc = pypdfium2.PdfDocument(covered.pdf)
    assert len(doc) == 1
    page = doc[0].render(scale=scan_mask.RENDER_SCALE).to_pil()
    scale = page.width / W
    box = tuple(int(v * scale) for v in NAME_BOX)
    region = page.crop((box[0] + int(220 * scale), box[1] + 8, box[2] - 30, box[3] - 8))
    assert min(region.convert("L").tobytes()) > 180
    assert doc[0].get_textpage().get_text_range().strip() == ""


def test_what_replaces_the_field_follows_the_rule(settings):
    key = b"k"
    fixed = scan_mask._replacement(rule("Full name", "fixed", "Hidden"), 4, key)
    fake = scan_mask._replacement(rule("Full name", "fake_name"), 4, key)
    assert fixed == "Hidden"
    assert fake.split(" ", 1)[0] in attachment_mask._FIRST_NAMES
    assert fake == scan_mask._replacement(rule("Full name", "fake_name"), 4, key)
    assert fake != scan_mask._replacement(rule("Full name", "fake_name"), 5, key)
    assert scan_mask._replacement(rule("Name and surname"), 12, key) == "NAME_AND_SURNAME_12"


def test_a_short_label_does_not_take_a_longer_word(settings):
    lines = [([(100, 200), (360, 200), (360, 230), (100, 230)], "Names of the films")]
    assert scan_mask._find_label(lines, "Name", set()) is None
    lines = [([(100, 200), (500, 200), (500, 230), (100, 230)], "Full name MARIO")]
    index, quad = scan_mask._find_label(lines, "Full name", set())
    assert index == 0 and 300 < quad[1][0] < 380        # cut where the label ends


def test_the_area_follows_a_skewed_scan(settings):
    slope = 0.02
    lines = [([(100, 80), (900, 96), (900, 126), (100, 110)], "Test award 2026 - Ballot form"),
             ([(100, 225), (300, 229), (300, 259), (100, 255)], "Full name")]
    assert abs(scan_mask._page_slope(lines) - slope) < 0.001
    zone, height = scan_mask._zone(lines[1][0], W, slope)
    (lx, ly), (rx, ry) = zone[0], zone[1]
    assert rx == W - 100 and abs((ry - ly) - slope * (rx - lx)) < 0.01
    assert height == pytest.approx(30, abs=1)


# ── numbers ──────────────────────────────────────────────────────────

def test_a_document_keeps_its_number(settings):
    a, b = b"%PDF first", b"%PDF second"
    assert scan_mask.number_for(1, a) == 1
    assert scan_mask.number_for(1, b) == 2
    assert scan_mask.number_for(1, a) == 1
    assert scan_mask.number_for(2, b) == 1            # each account counts its own


# ── read_attachment ──────────────────────────────────────────────────

@pytest.fixture
def scanned(monkeypatch, settings):
    """read_attachment serves the scanned ballot; the OCR is the stand-in."""
    pdf = as_pdf(ballot())
    monkeypatch.setattr(server.core_accounts, "get_active_account", lambda: {"id": 1})
    monkeypatch.setattr(server.mail_router, "get_attachment", lambda **kw: pdf)
    monkeypatch.setattr(scan_mask, "available", lambda: True)
    monkeypatch.setattr(scan_mask, "_default_ocr", fake_ocr)
    return pdf


def test_a_scan_is_left_alone_when_the_switch_is_off(scanned):
    r = server.read_attachment(message_id="42", filename="mario-rossi.pdf")
    assert r == {"filename": "mario-rossi.pdf", "kind": "pdf", "text": ""}


def test_a_scan_gets_a_covered_copy_named_by_its_number(scanned, tmp_path):
    attachment_mask.set_enabled(1, True)
    attachment_mask.save_field_rules(1, [rule("Full name")])
    r = server.read_attachment(message_id="42", filename="mario-rossi.pdf")
    assert r["text"] == "" and r["masked"] is True
    assert r["covered_fields"] == ["Full name -> FULL_NAME_1"]
    path = r["covered_copy"]
    assert path.startswith(str(tmp_path)) and path.endswith("document-0001.pdf")
    assert "mario" not in path.lower()
    assert open(path, "rb").read().startswith(b"%PDF")
    # Read again: the same number, the same file.
    assert server.read_attachment(message_id="42", filename="x.pdf")["covered_copy"] == path


def test_a_scan_with_a_missing_field_saves_nothing(scanned, tmp_path):
    attachment_mask.set_enabled(1, True)
    attachment_mask.save_field_rules(1, [rule("Full name"), rule("Tax code")])
    r = server.read_attachment(message_id="42", filename="ballot.pdf")
    assert "covered_copy" not in r and r["fields_not_found"] == ["Tax code"]
    assert list(tmp_path.rglob("*.pdf")) == []


def test_a_scan_without_rules_or_without_the_component_says_so(scanned, monkeypatch, tmp_path):
    attachment_mask.set_enabled(1, True)
    r = server.read_attachment(message_id="42", filename="ballot.pdf")
    assert "no fields to cover" in r["note"] and "covered_copy" not in r
    attachment_mask.save_field_rules(1, [rule("Full name")])
    monkeypatch.setattr(scan_mask, "available", lambda: False)
    r = server.read_attachment(message_id="42", filename="ballot.pdf")
    assert "not installed" in r["note"] and "covered_copy" not in r
    assert list(tmp_path.rglob("*.pdf")) == []


def test_a_failure_while_covering_saves_nothing(scanned, monkeypatch, tmp_path):
    def broken(*a, **kw):
        raise RuntimeError("ocr down")
    attachment_mask.set_enabled(1, True)
    attachment_mask.save_field_rules(1, [rule("Full name")])
    monkeypatch.setattr(scan_mask, "cover_pdf", broken)
    r = server.read_attachment(message_id="42", filename="ballot.pdf")
    assert "failed" in r["note"] and "covered_copy" not in r
    assert list(tmp_path.rglob("*.pdf")) == []


# ── the real OCR ─────────────────────────────────────────────────────

def test_printed_labels_are_found_by_the_real_ocr(settings):
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import ImageFont
    img = ballot()
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=30)
    d.text((100, 80), "Test award 2026 - Ballot", font=font, fill=(20, 20, 20))
    d.text((100, 222), "Full name", font=font, fill=(20, 20, 20))
    d.text((100, 522), "Best film", font=font, fill=(20, 20, 20))
    replaced, missing = scan_mask.cover_images([img], [rule("Full name")], 1, b"k")
    assert missing == [] and replaced == ["Full name -> FULL_NAME_1"]
    assert ink(img, VOTE_BOX) > 500
    region = img.crop((NAME_BOX[0] + 220, NAME_BOX[1] + 8, NAME_BOX[2] - 20, NAME_BOX[3] - 8))
    assert min(region.convert("L").tobytes()) > 200
