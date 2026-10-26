"""The demo request forms on the public site must have somewhere to go.

With both `endpoint` and `email` empty the form only shows "not configured"
and the request is lost without a trace.
"""
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"


@pytest.mark.parametrize("page", ["business", "real-estate"])
def test_demo_form_has_a_destination(page):
    source = (DOCS / page / "config.js").read_text(encoding="utf-8")
    fields = dict(re.findall(r"(endpoint|email):\s*'([^']*)'", source))
    assert set(fields) == {"endpoint", "email"}
    assert fields["endpoint"] or fields["email"]
    if fields["email"]:
        assert re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", fields["email"])
