"""ade_masker: detect / mask / unmask round-trip."""
from ade_mail_agent.core import ade_masker

TESTO = (
    "Buongiorno, l'IBAN e' IT60X0542811101000000123456, "
    "mi chiami al 333 1234567 o scriva a mario.rossi@example.it. "
    "CF: RSSMRA80A01H501U"
)


def test_detect_trova_entita_sensibili():
    ents = ade_masker.detect(TESTO)
    values = " ".join(e.get("value", "") for e in ents)
    assert "IT60X0542811101000000123456" in values
    assert "mario.rossi@example.it" in values


def test_mask_unmask_roundtrip():
    masked, mapping = ade_masker.mask(TESTO)
    assert "IT60X0542811101000000123456" not in masked
    assert "mario.rossi@example.it" not in masked
    restored = ade_masker.unmask(masked, mapping)
    assert restored == TESTO


def test_mask_selettivo():
    masked, mapping = ade_masker.mask(TESTO, selected_values=["mario.rossi@example.it"])
    assert "mario.rossi@example.it" not in masked
    # il resto rimane in chiaro se non selezionato
    assert "IT60X0542811101000000123456" in masked


def test_user_masks_per_account():
    created = ade_masker.add_user_mask(999, "Progetto Fenice", label_type="PROGETTO")
    assert created
    masks = ade_masker.get_user_masks(999)
    assert any(m.get("value") == "Progetto Fenice" for m in masks)
    # altro account: isolamento
    assert not any(m.get("value") == "Progetto Fenice"
                   for m in ade_masker.get_user_masks(998))
    mid = next(m["id"] for m in masks if m.get("value") == "Progetto Fenice")
    assert ade_masker.delete_user_mask(999, mid) is True
