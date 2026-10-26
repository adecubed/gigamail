"""Plain text from mail HTML: no Outlook CSS, no raw entities."""
from gigamail.core.html_text import html_to_text

OUTLOOK = (
    '<html><head><!--[if !mso]><style>v\\:* {behavior:url(#default#VML);}\n'
    'o\\:* {behavior:url(#default#VML);}\n.shape {behavior:url(#default#VML);}\n'
    '</style><![endif]--><style><!-- p.MsoNormal {margin:0cm;} --></style></head>'
    '<body><p>Hi Mario,</p><p>&nbsp;</p><p>Searches for &quot;eligibility&quot; '
    '&amp; more.</p></body></html>'
)


def test_outlook_style_blocks_and_entities_are_gone():
    text = html_to_text(OUTLOOK)
    assert text == 'Hi Mario, Searches for "eligibility" & more.'
    assert "behavior" not in text and "&nbsp;" not in text


def test_keep_lines_keeps_paragraphs():
    text = html_to_text(OUTLOOK, keep_lines=True)
    assert text.splitlines()[0] == "Hi Mario,"
    assert 'Searches for "eligibility" & more.' in text


def test_empty_and_plain_input():
    assert html_to_text("") == ""
    assert html_to_text(None) == ""
    assert html_to_text("just text") == "just text"
