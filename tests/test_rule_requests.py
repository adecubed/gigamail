import os

import pytest

from gigamail.core import attachments, rule_requests


def test_create_cleans_senders_and_keeps_only_known_fields(tmp_path):
    out = rule_requests.clean_create(1, {
        "trigger_kind": "senders", "trigger_values": [" Mario.Rossi@Example.com ", ""],
        "mode": "semi", "reply_style": "short", "reply_to_body_address": True})
    assert out["trigger_values"] == ["mario.rossi@example.com"]
    assert "reply_to_body_address" not in out
    assert out["first_contact"] == "semi" and out["daily_cap"] == 10
    assert out["cooldown_hours"] == 4.0 and out["expiry_days"] == 30.0


@pytest.mark.parametrize("fields,message", [
    ({"trigger_kind": "subject", "trigger_values": ["x"], "mode": "semi"}, "trigger_kind"),
    ({"trigger_kind": "senders", "trigger_values": [" "], "mode": "semi"}, "trigger"),
    ({"trigger_kind": "senders", "trigger_values": ["a@example.com"], "mode": "fast"}, "mode"),
])
def test_create_refuses_what_the_console_refuses(fields, message):
    with pytest.raises(ValueError, match=message):
        rule_requests.clean_create(1, fields)


def test_update_keeps_only_what_was_sent_and_needs_something():
    rule = {"account_id": 1, "trigger_kind": "senders", "trigger_values": ["a@example.com"]}
    assert rule_requests.clean_update(rule, {"daily_cap": 3, "mode": None}) == {"daily_cap": 3}
    with pytest.raises(ValueError, match="nothing to change"):
        rule_requests.clean_update(rule, {"mode": None})


def test_update_of_the_trigger_kind_carries_the_values():
    rule = {"account_id": 1, "trigger_kind": "senders", "trigger_values": ["a@example.com"]}
    out = rule_requests.clean_update(rule, {"trigger_kind": "folder", "trigger_values": ["INBOX.Leads"]})
    assert out == {"trigger_kind": "folder", "trigger_values": ["INBOX.Leads"]}


WIN_DOCS = "C:\\Users\\mario\\"
POSIX_DOCS = "/home/mario/"


def _shapes(rest):
    """The same relative path in Windows and POSIX shape: the dot and AppData
    rules look at the string only, so both shapes run on every platform."""
    return [WIN_DOCS + rest.replace("/", "\\"), POSIX_DOCS + rest]


@pytest.mark.parametrize("rest", [
    "Documents/prices.pdf", "Desktop/prices.pdf", "Downloads/prices.pdf",
    "OneDrive/Documents/prices.pdf"])
def test_excluded_reason_accepts_user_folders(rest):
    for path in _shapes(rest):
        assert rule_requests.excluded_reason(path) == ""


@pytest.mark.parametrize("rest", [
    ".ssh/id_rsa.txt", ".SSH/id_rsa.txt", "Documents/.notes.txt",
    "AppData/Roaming/notes.txt", "appdata/Roaming/notes.txt",
    "APPDATA/Roaming/notes.txt"])
def test_excluded_reason_refuses_dot_components_and_appdata(rest):
    for path in _shapes(rest):
        assert rule_requests.excluded_reason(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows system folders apply on Windows only")
@pytest.mark.parametrize("var", ["SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"])
def test_excluded_reason_refuses_windows_system_folders(monkeypatch, var):
    monkeypatch.setenv(var, "C:\\Fake" + var.replace("(", "").replace(")", ""))
    root = os.environ[var]
    assert rule_requests.excluded_reason(root + "\\Sub\\x.txt")
    assert rule_requests.excluded_reason(root.lower() + "\\x.txt")
    assert rule_requests.excluded_reason(root + "2\\x.txt") == ""


@pytest.mark.skipif(os.name == "nt", reason="POSIX system folders apply off Windows only")
@pytest.mark.parametrize("root", ["/etc", "/usr", "/bin", "/sbin", "/var", "/private",
                                  "/System", "/Library"])
def test_excluded_reason_refuses_posix_system_folders(root):
    assert rule_requests.excluded_reason(root + "/sub/x.txt")
    assert rule_requests.excluded_reason(root + "x/y.txt") == ""


@pytest.fixture
def allowed_path(tmp_path, monkeypatch):
    """A real file that realpath reports under an allowed folder (tmp_path
    sits under AppData on Windows, which would refuse it for that reason)."""
    real_realpath = os.path.realpath
    real_exists = os.path.exists

    def make(name, folder="Documents"):
        target = tmp_path / name
        target.write_text("x")
        fake = _shapes(folder + "/" + name)[0 if os.name == "nt" else 1]
        monkeypatch.setattr(os.path, "realpath",
                            lambda p, *a, **k: fake if str(p) == str(target)
                            else real_realpath(p, *a, **k))
        # the real path stands for the file: it exists as the file does
        monkeypatch.setattr(os.path, "exists",
                            lambda p: True if str(p) == fake else real_exists(p))
        make.real = fake
        return str(target)
    return make


def test_an_allowed_document_is_accepted_end_to_end(allowed_path):
    target = allowed_path("prices.txt")
    assert rule_requests.is_allowed_doc(target) == (True, "")
    # stored as the real path that was checked, not the path as given
    assert rule_requests.clean_docs(1, [target], guard=True) == [allowed_path.real]
    assert allowed_path.real != os.path.abspath(target)


def test_a_document_is_refused_end_to_end_by_the_dot_rule(allowed_path):
    """Removing the call to excluded_reason from the guard fails this test:
    the path given is fine, only what it resolves to sits in a dot folder."""
    target = allowed_path("id_rsa.txt", folder=".ssh")
    ok, why = rule_requests.is_allowed_doc(target)
    assert ok is False and "dot" in why
    with pytest.raises(ValueError, match="dot"):
        rule_requests.clean_docs(1, [target], guard=True)


def test_a_missing_guarded_document_is_refused_in_english(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "resolve", lambda aid, names: ([], list(names)))
    with pytest.raises(ValueError, match="no such document: prices.txt"):
        rule_requests.clean_docs(1, ["prices.txt"], guard=True)
    with pytest.raises(ValueError, match="Documento inesistente"):
        rule_requests.clean_docs(1, [str(tmp_path / "missing.txt")], guard=False)


@pytest.mark.parametrize("path", [
    "/private/etc/hosts.txt", "/private/var/db/x.txt", "/Users/mario/Library/Mail/x.txt",
    "/Users/mario/library/Messages/x.txt", "/PRIVATE/etc/x.txt"])
def test_macos_shapes_of_system_folders_and_the_home_library_are_refused(path):
    import posixpath
    assert rule_requests.folder_reason(path, posixpath, rule_requests._POSIX_SYSTEM_DIRS,
                                       "/Users/mario")


@pytest.mark.parametrize("path", [
    "/Users/mario/Documents/Library/x.txt", "/Users/mario/Librarian/x.txt",
    "/privatex/x.txt", "/Users/mario/Documents/prices.pdf"])
def test_a_library_folder_elsewhere_is_allowed(path):
    import posixpath
    assert rule_requests.folder_reason(path, posixpath, rule_requests._POSIX_SYSTEM_DIRS,
                                       "/Users/mario") == ""


@pytest.mark.skipif(os.name == "nt", reason="the POSIX guard runs off Windows only")
def test_the_guard_refuses_private_and_the_home_library_here(monkeypatch):
    monkeypatch.setenv("HOME", "/Users/mario")
    assert rule_requests.excluded_reason("/private/etc/hosts")
    assert rule_requests.excluded_reason("/Users/mario/Library/Keychains/x.txt")


def test_a_program_is_refused(allowed_path):
    ok, why = rule_requests.is_allowed_doc(allowed_path("setup.exe"))
    assert ok is False and "program" in why


def test_gigamail_data_is_refused(allowed_path, monkeypatch):
    target = allowed_path("tokens.txt")
    monkeypatch.setattr(attachments, "is_gigamail_data", lambda real: True)
    ok, why = rule_requests.is_allowed_doc(target)
    assert ok is False and "GigaMail" in why
    with pytest.raises(ValueError):
        rule_requests.clean_docs(1, [target], guard=True)


def test_a_link_resolving_to_a_network_path_is_refused(monkeypatch):
    monkeypatch.setattr(os.path, "realpath", lambda p, *a, **k: r"\\server\share\x.pdf")
    ok, why = rule_requests.is_allowed_doc("link.pdf")
    assert ok is False and "network" in why


def test_a_guarded_document_on_a_network_path_is_refused_without_touching_it():
    assert rule_requests.is_allowed_doc(r"\\server\share\prices.pdf")[0] is False


def test_an_unguarded_document_keeps_the_console_behaviour(tmp_path):
    target = tmp_path / ".hidden" / "prices.txt"
    target.parent.mkdir()
    target.write_text("x")
    assert rule_requests.clean_docs(1, [str(target)], guard=False) == [str(target)]
    with pytest.raises(ValueError):
        rule_requests.clean_docs(1, [str(tmp_path / "missing.txt")], guard=False)


def test_a_guarded_knowledge_file_name_becomes_its_path(tmp_path, monkeypatch):
    real = tmp_path / "prices.txt"
    real.write_text("x")

    def fake_resolve(account_id, names):
        return ([{"name": n, "path": str(real)} for n in names if n == "prices.txt"],
                [n for n in names if n != "prices.txt"])
    monkeypatch.setattr(attachments, "resolve", fake_resolve)
    assert rule_requests.clean_docs(1, ["prices.txt"], guard=True) == [str(real)]
    with pytest.raises(ValueError, match="nope.txt"):
        rule_requests.clean_docs(1, ["nope.txt"], guard=True)


def test_attachments_must_be_registered(monkeypatch):
    monkeypatch.setattr(attachments, "resolve",
                        lambda aid, names: ([], list(names)))
    with pytest.raises(ValueError, match="Allegati non registrati.*plan.pdf"):
        rule_requests.clean_create(1, {
            "trigger_kind": "folder", "trigger_values": ["INBOX.Leads"],
            "mode": "semi", "attachments": ["plan.pdf"]})


# --- previews of a rule request -------------------------------------------

from gigamail import policy  # noqa: E402

FULL_RULE = {
    "account_id": 1, "trigger_kind": "senders", "trigger_values": ["mario.rossi@example.com"],
    "mode": "auto", "first_contact": "semi", "reply_style": "short and kind",
    "doc_paths": ["C:/docs/prices.pdf"], "attachments": ["plan.pdf"], "cc": [],
    "daily_cap": 10, "cooldown_hours": 4.0, "expiry_days": 30.0}


def test_a_new_auto_rule_says_so_in_title_and_text(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    p = rule_requests.preview("create", FULL_RULE, account_label="info@example.com")
    assert p["action"] == "rule_create" and p["rule_id"] is None
    assert p["subject"] == "New AUTO rule for mario.rossi@example.com"
    for piece in ("info@example.com", "AUTO — replies on its own", "short and kind",
                  "C:/docs/prices.pdf", "plan.pdf", "10", "30"):
        assert piece in p["body"]
    assert "10.0" not in p["body"] and "4.0" not in p["body"] and "30.0" not in p["body"]


def test_a_new_rule_is_described_in_italian(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    p = rule_requests.preview("create", FULL_RULE, account_label="info@example.com")
    assert p["subject"] == "Nuova regola AUTO per mario.rossi@example.com"
    lines = p["body"].splitlines()
    assert lines[0] == "Account: info@example.com"
    assert "Mittenti:" in lines and "  • mario.rossi@example.com" in lines
    assert "AUTO — risponde da sola, senza chiederti" in p["body"]
    assert "SEMI — prepara la risposta e aspetta la tua approvazione" in p["body"]
    assert "Tetto giornaliero: 10" in p["body"]
    assert "Attesa per mittente: 4" in p["body"] and "Durata: 30" in p["body"]


def test_describe_marks_empty_values_and_lists_documents_one_per_line(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    empty = rule_requests.describe({"trigger_kind": "folder", "trigger_values": ["INBOX.Leads"],
                                    "reply_style": "", "doc_paths": []})
    assert empty.splitlines()[:2] == ["Folder:", "  • INBOX.Leads"]
    assert "Documents: (none)" in empty
    two = rule_requests.describe({"doc_paths": ["a.pdf", "b.pdf"]})
    assert two.splitlines() == ["Documents:", "  • a.pdf", "  • b.pdf"]
    assert rule_requests.describe({}) == ""


def test_a_title_counts_the_other_triggers(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    rule = dict(FULL_RULE, mode="semi",
                trigger_values=["a@example.com", "b@example.com", "c@example.com"])
    assert rule_requests.preview("create", rule)["subject"] == \
        "New SEMI rule for a@example.com (+2)"


def test_an_update_shows_only_what_changes_and_warns_about_auto(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    before = {"rule_id": "rule_1", "mode": "semi", "daily_cap": 10, "reply_style": "short"}
    p = rule_requests.preview("update", {"mode": "auto", "daily_cap": 3}, before=before)
    assert p["body"].splitlines()[0].startswith("⚠")
    assert "semi → auto" in p["body"] and "10 → 3" in p["body"]
    assert "short" not in p["body"]
    assert p["rule_id"] == "rule_1" and p["subject"] == "Change rule rule_1"


def test_an_update_leaves_out_a_field_equal_to_its_old_value(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    before = {"rule_id": "rule_1", "mode": "semi", "daily_cap": 10,
              "trigger_kind": "senders", "trigger_values": ["a@example.com"]}
    p = rule_requests.preview("update", {"daily_cap": 5, "mode": "semi",
                                         "trigger_values": ["a@example.com", "b@example.com"]},
                              before=before)
    assert not p["body"].startswith("⚠") and "⚠" not in p["body"]
    # the mode is not a change: it is shown as the rule's current mode only
    assert "5" in p["body"] and "Mode: SEMI — prepares" in p["body"]
    assert not any(ln.startswith("Mode:") and "→" in ln for ln in p["body"].splitlines())
    assert p["body"].splitlines()[-5:] == [
        "Senders, before:", "  • a@example.com", "Senders, after:", "  • a@example.com",
        "  • b@example.com"][-5:]
    same = rule_requests.preview("update", {"daily_cap": 10.0}, before=before)
    assert "Daily cap" not in same["body"]


def test_an_update_to_something_else_than_auto_has_no_warning(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    before = {"rule_id": "rule_1", "mode": "auto", "first_contact": "auto", "daily_cap": 10}
    p = rule_requests.preview("update", {"mode": "auto", "first_contact": "semi",
                                         "daily_cap": 2}, before=before)
    assert "⚠" not in p["body"]


def test_first_contact_going_to_auto_warns_in_italian(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    before = {"rule_id": "rule_1", "mode": "semi", "first_contact": "semi"}
    p = rule_requests.preview("update", {"first_contact": "auto"}, before=before)
    assert p["body"].splitlines()[0] == (
        "⚠ La regola diventa AUTOMATICA: risponderà da sola, senza chiederti.")
    assert "Primo contatto: semi → auto" in p["body"]


@pytest.mark.parametrize("lang,expected", [
    ("en", {"resume": "Resume AUTO rule for mario.rossi@example.com (rule_1)",
            "renew": "Renew AUTO rule for mario.rossi@example.com for 30 days (rule_1)",
            "delete": "Delete AUTO rule for mario.rossi@example.com (rule_1)"}),
    ("it", {"resume": "Riattiva regola AUTO per mario.rossi@example.com (rule_1)",
            "renew": "Rinnova regola AUTO per mario.rossi@example.com per 30 giorni (rule_1)",
            "delete": "Elimina regola AUTO per mario.rossi@example.com (rule_1)"}),
])
def test_resume_renew_and_delete_titles(monkeypatch, lang, expected):
    monkeypatch.setattr(policy, "user_lang", lambda: lang)
    rule = dict(FULL_RULE, rule_id="rule_1")
    for action, title in expected.items():
        p = rule_requests.preview(action, rule, account_label="info@example.com")
        assert p["subject"] == title
        assert p["action"] == "rule_" + action and p["rule_id"] == "rule_1"
        assert "mario.rossi@example.com" in p["body"] and "info@example.com" in p["body"]


def test_an_unknown_action_is_refused():
    with pytest.raises(ValueError):
        rule_requests.preview("explode", FULL_RULE)


def test_every_channel_text_carries_the_title_and_the_body(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    p = rule_requests.preview("create", FULL_RULE, account_label="info@example.com")
    text = policy.full_preview_text("create_rule", p)
    assert p["subject"] in text and "AUTO — replies on its own" in text
    assert "C:/docs/prices.pdf" in text


# --- untrusted text, order, and the finer points -----------------------------

BLOCK = "  │ "


def test_a_forged_line_in_the_instruction_stays_inside_its_block(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    rule = dict(FULL_RULE, cc=["real@example.com"], daily_cap=7,
                reply_style="x\nCc: boss@example.com\nDaily cap: 1")
    body = rule_requests.preview("create", rule)["body"]
    lines = body.splitlines()
    assert "  • real@example.com" in lines and "Daily cap: 7" in lines
    for line in lines:
        if "boss@example.com" in line or "Daily cap: 1" in line:
            assert line.startswith(BLOCK)
        assert line != "Cc: boss@example.com" and not line.startswith("Cc: boss@example.com")
        assert not line.startswith("Daily cap: 1")


def test_values_with_newlines_render_on_one_line(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    rule = dict(FULL_RULE, trigger_values=["a@example.com\nCc: x@example.com"],
                doc_paths=["my\n  doc.pdf"])
    lines = rule_requests.describe(rule, "info\n@example.com").splitlines()
    assert "Account: info @example.com" in lines
    assert "  • a@example.com Cc: x@example.com" in lines
    assert "  • my doc.pdf" in lines


def test_a_long_value_is_cut_with_an_ellipsis(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    line = rule_requests.describe({"trigger_kind": "folder",
                                   "trigger_values": ["f" * 500]}).splitlines()[0]
    assert line == "Folder:"
    assert rule_requests.describe({"trigger_kind": "folder", "trigger_values": ["f" * 500]}
                                  ).splitlines()[1] == "  • " + "f" * 199 + "…"


def test_a_huge_instruction_cannot_push_the_fields_out(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    rule = dict(FULL_RULE, cc=["real@example.com"], reply_style="word " * 1000)
    p = rule_requests.preview("create", rule)
    lines = p["body"].splitlines()
    label = lines.index("Instruction:")
    for start in ("Cc:", "Fixed attachments:", "Documents:", "Daily cap:", "Lasts:", "Senders:"):
        assert [i for i, ln in enumerate(lines) if ln.startswith(start)][0] < label
    text = policy.full_preview_text("create_rule", p)
    for piece in ("  • real@example.com", "  • plan.pdf", "Daily cap: 10"):
        assert piece in text


def test_an_empty_instruction_stays_on_the_label_line(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    assert rule_requests.describe({"reply_style": ""}) == "Istruzione: (nessuna)"


def test_a_changed_instruction_is_two_blocks_at_the_end(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    before = {"rule_id": "rule_1", "reply_style": "old\nline", "daily_cap": 10}
    p = rule_requests.preview("update", {"reply_style": "new", "daily_cap": 3}, before=before)
    assert p["body"].splitlines() == [
        "Daily cap: 10 → 3", "Instruction, before:", BLOCK + "old", BLOCK + "line",
        "Instruction, after:", BLOCK + "new"]


def test_a_semi_rule_that_sends_to_new_senders_says_so(monkeypatch):
    rule = dict(FULL_RULE, mode="semi", first_contact="auto")
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    assert rule_requests.preview("create", rule)["subject"] == \
        "New SEMI rule (first contact AUTO) for mario.rossi@example.com"
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    assert rule_requests.preview("create", rule)["subject"] == \
        "Nuova regola SEMI (primo contatto AUTO) per mario.rossi@example.com"


def test_the_account_line_falls_back_to_the_id(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    assert rule_requests.describe({"account_id": 3}).splitlines() == ["Account: #3"]
    assert rule_requests.describe({"account_id": 3}, "info@example.com") == \
        "Account: info@example.com"
    assert rule_requests.describe({"daily_cap": 1}) == "Daily cap: 1"
    p = rule_requests.preview("update", {"daily_cap": 2},
                              before={"rule_id": "r", "account_id": 3, "daily_cap": 1})
    assert p["body"].splitlines() == ["Account: #3", "Daily cap: 1 → 2"]


@pytest.mark.parametrize("days,n", [(30.0, 30), (0.4, 1), (2.6, 3)])
def test_renew_rounds_to_whole_days_with_a_minimum_of_one(monkeypatch, days, n):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    p = rule_requests.preview("renew", {"rule_id": "r", "expiry_days": days})
    assert p["subject"] == f"Renew SEMI rule r for {n} days"


@pytest.mark.parametrize("rule", [{"rule_id": "r"}, {"rule_id": "r", "expiry_days": 0},
                                  {"rule_id": "r", "expiry_days": -3}])
def test_renew_without_a_duration_is_refused(rule):
    with pytest.raises(ValueError, match="rule has no duration"):
        rule_requests.preview("renew", rule)


def test_diff_lines_have_units_and_show_both_lists(monkeypatch):
    before = {"rule_id": "r", "cooldown_hours": 4.0, "expiry_days": 30, "cc": ["a@example.com"],
              "doc_paths": ("one.pdf",), "attachments": ["x.pdf"]}
    change = {"cooldown_hours": 6.0, "expiry_days": 60, "cc": ["b@example.com"],
              "doc_paths": ["one.pdf", "two.pdf"], "attachments": ["x.pdf"]}
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    body = rule_requests.preview("update", change, before=before)["body"]
    assert "Wait per sender: 4 hours → 6 hours" in body
    assert "Lasts: 30 days → 60 days" in body
    assert body.splitlines()[-9:] == [
        "Cc, before:", "  • a@example.com", "Cc, after:", "  • b@example.com",
        "Documents, before:", "  • one.pdf", "Documents, after:", "  • one.pdf",
        "  • two.pdf"]
    assert "Fixed attachments" not in body
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    assert "Attesa per mittente: 4 ore → 6 ore" in \
        rule_requests.preview("update", change, before=before)["body"]


def test_a_long_list_cannot_push_the_fixed_lines_out(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    senders = [f"{i:02d}" + "s" * 198 for i in range(30)]
    rule = dict(FULL_RULE, trigger_values=senders, cc=["real@example.com"])
    p = rule_requests.preview("create", rule)
    text = policy.full_preview_text("create_rule", p)
    for piece in ("Mode: AUTO", "Daily cap: 10", "Wait per sender: 4 hours", "Lasts: 30 days"):
        assert piece in text
    for piece in ("Cc:", "  • real@example.com", "  • plan.pdf"):
        assert piece in text
    for value in senders:
        assert "  • " + value in p["body"]


def test_no_list_item_can_start_a_line_like_a_field(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    rule = {"doc_paths": ["a.pdf", "Cc: boss@example.com"]}
    lines = rule_requests.describe(rule).splitlines()
    assert not any(ln.startswith("Cc: boss@example.com") for ln in lines)
    assert "  • Cc: boss@example.com" in lines


def test_a_single_item_is_prefixed_too(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    lines = rule_requests.describe({"trigger_values": ["a@example.com"],
                                    "doc_paths": ["one.pdf"], "cc": []}).splitlines()
    assert lines == ["Cc: (none)", "Senders:", "  • a@example.com", "Documents:", "  • one.pdf"]


def test_an_update_of_the_trigger_and_cc_shows_every_item_before_and_after(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    before = {"rule_id": "r", "trigger_kind": "senders", "trigger_values": ["a@example.com"],
              "cc": []}
    change = {"trigger_values": ["b@example.com", "c@example.com"], "cc": ["d@example.com"]}
    assert rule_requests.preview("update", change, before=before)["body"].splitlines() == [
        "Cc, prima: (nessuno)", "Cc, dopo:", "  • d@example.com",
        "Mittenti, prima:", "  • a@example.com",
        "Mittenti, dopo:", "  • b@example.com", "  • c@example.com"]


def test_bidirectional_controls_are_shown_as_a_replacement_character(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    controls = [chr(c) for c in (0x202E, 0x2066, 0x200F, 0x061C)]
    body = rule_requests.describe({"trigger_values": ["a" + controls[0] + "@example.com"],
                                   "reply_style": "x" + controls[1] + "y" + controls[2]},
                                  "in" + controls[3] + "fo")
    assert not any(c in body for c in controls)
    assert "  • a�@example.com" in body and "Account: in�fo" in body
    assert rule_requests.BLOCK_PREFIX + "x�y�" in body.splitlines()


TAGS = "Open 9-18" + "".join(chr(0xE0000 + ord(c)) for c in "bcc x@example.com")
INVISIBLE = [chr(0x200B), chr(0xFEFF), chr(0x00AD), chr(0x2060), chr(0xE0100), chr(0xE01EF),
             chr(0xE0001)]


@pytest.mark.parametrize("value", [TAGS] + ["Reply" + c + "politely" for c in INVISIBLE])
def test_an_instruction_with_invisible_format_characters_is_refused(value):
    with pytest.raises(ValueError, match="reply_style"):
        rule_requests.check_agent_limits({"reply_style": value})


@pytest.mark.parametrize("code", [0x200B, 0xFEFF, 0x00AD, 0x2060, 0xE0062, 0xE0100])
def test_an_item_with_an_invisible_format_character_is_refused(code):
    with pytest.raises(ValueError, match="cc"):
        rule_requests.check_agent_limits({"cc": ["a" + chr(code) + "b@example.com"]})


@pytest.mark.parametrize("emoji", ["\U0001F469‍\U0001F4BB", "❤️",
                                   "a‌b"])
def test_joiners_and_emoji_presentation_are_accepted(emoji):
    assert not any(rule_requests.bad_char(ch) for ch in emoji)
    rule_requests.check_agent_limits({"reply_style": "Thanks " + emoji})


FILLERS = [0x3164, 0x115F, 0x1160, 0xFFA0, 0x2800, 0x034F, 0x17B4, 0x17B5, 0x16FE4]


@pytest.mark.parametrize("code", FILLERS)
def test_a_blank_looking_filler_is_refused(code):
    """Neither whitespace nor a format character, but drawn as a space or
    as nothing: a rule's instruction or item could carry hidden text."""
    assert rule_requests.bad_char(chr(code))
    with pytest.raises(ValueError, match="reply_style"):
        rule_requests.check_agent_limits({"reply_style": "Reply" + chr(code) * 3 + "politely"})
    with pytest.raises(ValueError, match="cc"):
        rule_requests.check_agent_limits({"cc": ["a" + chr(code) + "b@example.com"]})


def test_a_stored_filler_is_shown_as_a_replacement_character():
    assert rule_requests.shown("Open" + chr(0x3164) + "9-18" + chr(0x2800)) == "Open�9-18�"


def test_a_stored_instruction_with_tag_characters_shows_a_replacement(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    body = rule_requests.describe({"reply_style": TAGS})
    assert chr(0xE0062) not in body and "�" in body
    assert all(not rule_requests.bad_char(ch) or ch == "\n" for ch in body)


def test_a_string_where_a_list_is_expected_is_one_item(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    lines = rule_requests.describe({"cc": "boss@example.com"}).splitlines()
    assert lines == ["Cc:", "  • boss@example.com"]
    p = rule_requests.preview("create", {"trigger_values": "a@example.com", "mode": "semi"})
    assert p["subject"] == "New SEMI rule for a@example.com"


def test_a_non_iterable_list_value_does_not_raise(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    assert rule_requests.describe({"doc_paths": 123}).splitlines() == ["Documents:", "  • 123"]
    assert rule_requests.describe({"cc": None}) == "Cc: (none)"
    assert rule_requests.describe({"cc": {"a@example.com"}}).splitlines()[1] ==         "  • a@example.com"


def test_empty_items_are_dropped(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    assert rule_requests.describe({"cc": ["a@example.com", " " + chr(10) + " ", ""]}).splitlines() == [
        "Cc:", "  • a@example.com"]
    assert rule_requests.describe({"cc": ["", " "]}) == "Cc: (none)"


def test_an_update_compares_lists_after_normalising(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    p = rule_requests.preview("update", {"cc": "a@example.com"},
                              before={"rule_id": "r", "cc": ["a@example.com"]})
    assert p["body"] == ""


def test_agent_limits_accept_what_is_at_the_limit():
    rule_requests.check_agent_limits({
        "trigger_values": ["a@example.com"] * rule_requests.AGENT_LIMITS["trigger_values"],
        "cc": ["a@example.com"] * rule_requests.AGENT_LIMITS["cc"],
        "doc_paths": ["x"] * rule_requests.AGENT_LIMITS["doc_paths"],
        "attachments": ["x"] * rule_requests.AGENT_LIMITS["attachments"],
        "reply_style": "x" * rule_requests.AGENT_MAX_INSTRUCTION})
    rule_requests.check_agent_limits({})


@pytest.mark.parametrize("field", ["trigger_values", "cc", "doc_paths", "attachments"])
def test_agent_limits_name_the_list_and_its_limit(field):
    limit = rule_requests.AGENT_LIMITS[field]
    with pytest.raises(ValueError, match=field) as info:
        rule_requests.check_agent_limits({field: ["x"] * (limit + 1)})
    assert str(limit) in str(info.value)


def test_agent_limits_cap_the_instruction():
    with pytest.raises(ValueError, match="reply_style") as info:
        rule_requests.check_agent_limits(
            {"reply_style": "x" * (rule_requests.AGENT_MAX_INSTRUCTION + 1)})
    assert str(rule_requests.AGENT_MAX_INSTRUCTION) in str(info.value)


def test_the_console_path_keeps_no_limit():
    many = [f"a{i}@example.com" for i in range(rule_requests.AGENT_LIMITS["trigger_values"] + 10)]
    out = rule_requests.clean_create(1, {"trigger_kind": "senders", "trigger_values": many})
    assert len(out["trigger_values"]) == len(many)


# --- what the agent may send: nothing the approval text could not show -------

NORMAL = {"trigger_kind": "senders", "trigger_values": ["mario.rossi@example.com"],
          "cc": ["anna.bianchi@example.com"], "doc_paths": ["C:/Users/mario/Documents/prices.pdf"],
          "attachments": ["Price list 2027.pdf"],
          "reply_style": "Reply in Italian.\n\tKeep it short.\nSign as Mario."}


def test_a_normal_request_from_the_agent_passes():
    rule_requests.check_agent_limits(NORMAL)
    rule_requests.check_agent_limits({"trigger_kind": "folder",
                                      "trigger_values": ["Clienti VIP"]})


@pytest.mark.parametrize("field", ["trigger_values", "cc", "doc_paths", "attachments"])
def test_an_item_longer_than_what_the_preview_shows_is_refused(field):
    cap = rule_requests._VALUE_MAX
    item = "a" * (cap - len("@example.com")) + "@example.com"
    rule_requests.check_agent_limits({field: [item]})
    with pytest.raises(ValueError, match=field):
        rule_requests.check_agent_limits({field: ["x" + item]})


def test_a_hidden_address_after_200_characters_is_refused():
    cc = "boss@example.com, " + "x" * 190 + ", hidden@example.com"
    with pytest.raises(ValueError, match="cc"):
        rule_requests.check_agent_limits({"cc": [cc]})


@pytest.mark.parametrize("field", ["trigger_values", "cc", "doc_paths", "attachments"])
@pytest.mark.parametrize("code", [0x0A, 0x09, 0x0D, 0x00, 0x85, 0x2028, 0x2029,
                                  0x202E, 0x2066, 0x200F, 0x061C])
def test_an_item_with_a_control_or_bidi_character_is_refused(field, code):
    with pytest.raises(ValueError, match=field):
        rule_requests.check_agent_limits({field: ["a" + chr(code) + "b@example.com"]})


@pytest.mark.parametrize("value", ["boss@example.com, hidden@example.com",
                                   "boss@example.com hidden@example.com",
                                   "boss@example.com,hidden@example.com"])
def test_one_address_per_item_in_cc_and_senders(value):
    with pytest.raises(ValueError, match="cc"):
        rule_requests.check_agent_limits({"cc": [value]})
    with pytest.raises(ValueError, match="trigger_values"):
        rule_requests.check_agent_limits({"trigger_values": [value]})
    # an update that keeps the rule's kind: the rule's kind decides
    with pytest.raises(ValueError, match="trigger_values"):
        rule_requests.check_agent_limits({"trigger_values": [value]}, kind="senders")
    rule_requests.check_agent_limits({"trigger_values": ["Clienti, VIP"]}, kind="folder")


def test_whitespace_that_would_show_as_one_space_is_refused():
    for item in ("Price  list.pdf", "Price" + chr(0xA0) + "list.pdf"):
        with pytest.raises(ValueError, match="attachments"):
            rule_requests.check_agent_limits({"attachments": [item]})


def test_all_list_items_together_have_a_limit():
    item = "a" * 188 + "@example.com"
    many = [str(i) + item[len(str(i)):] for i in range(50)]
    with pytest.raises(ValueError, match=str(rule_requests.AGENT_MAX_LIST_CHARS)):
        rule_requests.check_agent_limits({"trigger_values": many})


def test_an_instruction_has_a_line_limit():
    lines = rule_requests.AGENT_MAX_INSTRUCTION_LINES
    rule_requests.check_agent_limits({"reply_style": "\n".join(["x"] * lines)})
    with pytest.raises(ValueError, match="reply_style") as info:
        rule_requests.check_agent_limits({"reply_style": "\n".join(["x"] * (lines + 1))})
    assert str(lines) in str(info.value)


@pytest.mark.parametrize("code", [0x0D, 0x00, 0x1B, 0x85, 0x202E, 0x2066, 0x200E])
def test_an_instruction_with_control_or_bidi_characters_is_refused(code):
    with pytest.raises(ValueError, match="reply_style"):
        rule_requests.check_agent_limits({"reply_style": "Reply" + chr(code) + "politely"})


def test_a_set_is_shown_sorted_and_none_items_are_dropped(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    for _ in range(3):
        assert rule_requests.describe({"cc": {"b@example.com", "a@example.com"}}).splitlines() \
            == ["Cc:", "  • a@example.com", "  • b@example.com"]
    assert rule_requests._as_list(frozenset({"z", "y"})) == ["y", "z"]
    assert rule_requests.describe({"cc": [None, "a@example.com"]}).splitlines() == [
        "Cc:", "  • a@example.com"]


# --- an update names the rule it changes -------------------------------------

RULE_BEFORE = {"rule_id": "rule_ab12cd34", "account_id": 1, "trigger_kind": "senders",
               "trigger_values": ["mario.rossi@example.com", "anna.bianchi@example.com"],
               "mode": "semi", "first_contact": "semi", "daily_cap": 10, "cc": [],
               "reply_style": "short"}


def test_an_update_names_the_rule_by_its_trigger_in_title_and_body(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    p = rule_requests.preview("update", {"daily_cap": 3}, before=RULE_BEFORE,
                              account_label="info@example.com")
    assert p["subject"] == "Change rule for mario.rossi@example.com (+1) (rule_ab12cd34)"
    assert p["body"].splitlines() == [
        "Account: info@example.com",
        "Mode: SEMI — prepares the reply and waits for your approval",
        "Daily cap: 10 → 3",
        "Senders:", "  • mario.rossi@example.com", "  • anna.bianchi@example.com"]


def test_an_update_that_makes_a_rule_automatic_says_which_rule(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "it")
    p = rule_requests.preview("update", {"mode": "auto"}, before=RULE_BEFORE)
    assert p["subject"] == "Modifica regola per mario.rossi@example.com (+1) (rule_ab12cd34)"
    lines = p["body"].splitlines()
    assert lines[0].startswith("⚠ La regola diventa AUTOMATICA")
    assert "Modalità: semi → auto" in lines
    assert not any(ln.startswith("Modalità: SEMI") for ln in lines)
    assert lines[-3:] == ["Mittenti:", "  • mario.rossi@example.com",
                          "  • anna.bianchi@example.com"]


def test_an_update_of_the_trigger_shows_it_before_and_after_only(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    p = rule_requests.preview("update", {"trigger_values": ["luca.verdi@example.com"]},
                              before=RULE_BEFORE)
    lines = p["body"].splitlines()
    assert "Senders:" not in lines
    assert lines[-5:] == ["Senders, before:", "  • mario.rossi@example.com",
                          "  • anna.bianchi@example.com", "Senders, after:",
                          "  • luca.verdi@example.com"]
    assert p["subject"] == "Change rule for mario.rossi@example.com (+1) (rule_ab12cd34)"


# --- the agent bar shows a rule request whole ---------------------------------

def _worst_lists(letter: str) -> dict:
    """The most the list limits allow, as stored: every document a resolved
    path at the display cap (a short knowledge-file name can resolve to
    one), and the rest of the characters in all spread over every other
    item allowed (each item costs a prefix and a line break)."""
    counts = rule_requests.AGENT_LIMITS
    cap = rule_requests._VALUE_MAX
    docs = counts["doc_paths"]
    others = sum(counts.values()) - docs
    size = (rule_requests.AGENT_MAX_LIST_CHARS - docs * cap) // others
    out, k = {}, 0
    for key, count in counts.items():
        items = []
        for _ in range(count):
            head = f"{letter}{k:03d}"
            k += 1
            if key == "doc_paths":
                start = "C:/Users/mario/Documents/" + head + "/"
                items.append(start + "d" * (cap - len(start) - 4) + ".pdf")
            else:
                items.append(head + "a" * (size - len(head) - 12) + "@example.com")
        out[key] = items
    assert all(len(p) == cap for p in out["doc_paths"])
    return out


def _worst_instruction(letter: str) -> str:
    lines = rule_requests.AGENT_MAX_INSTRUCTION_LINES
    width = rule_requests.AGENT_MAX_INSTRUCTION // lines
    return "\n".join([letter * (width - 1)] * lines)


def test_the_largest_rule_request_fits_the_agent_bar_card(monkeypatch):
    """The card shows a rule request whole whatever its length; the agent
    limits, measured on what is stored, keep the largest request the agent
    can make (an update showing before and after included) within the size
    of a mail's card text."""
    from gigamail.http_api import agent as agent_api
    monkeypatch.setattr(policy, "user_lang", lambda: "it")   # the longer labels
    before = {"rule_id": "rule_ab12cd34", "account_id": 1, "trigger_kind": "senders",
              "mode": "semi", "first_contact": "semi", "daily_cap": 1,
              "cooldown_hours": 1.0, "expiry_days": 1.0,
              "reply_style": _worst_instruction("b"), **_worst_lists("b")}
    after = {"trigger_kind": "folder", "mode": "auto", "first_contact": "auto",
             "daily_cap": 99999, "cooldown_hours": 99999.5,
             "reply_style": _worst_instruction("c"), **_worst_lists("c")}
    after["trigger_values"] = [v.replace("@", "-") for v in after["trigger_values"]]
    rule_requests.check_agent_limits(before)
    rule_requests.check_agent_limits(after)
    assert len(before["reply_style"]) <= rule_requests.AGENT_MAX_INSTRUCTION
    label = "x" * rule_requests._VALUE_MAX
    update = rule_requests.preview("update", after, before=before, account_label=label)
    create = rule_requests.preview("create", {**before, "expiry_days": 99999.5},
                                   account_label=label)
    for p in (update, create):
        assert len(p["body"]) <= agent_api.CARD_BODY_MAX, len(p["body"])
    # every item is there, uncut
    for value in before["cc"] + after["cc"] + after["trigger_values"] + after["doc_paths"]:
        assert "  • " + value in update["body"]


def test_an_update_shows_the_change_before_the_rule_it_leaves_alone(monkeypatch):
    monkeypatch.setattr(policy, "user_lang", lambda: "en")
    p = rule_requests.preview("update", {"cc": ["luca.verdi@example.com"],
                                         "reply_style": "longer", "daily_cap": 3},
                              before=RULE_BEFORE)
    assert p["body"].splitlines() == [
        "Account: #1",
        "Mode: SEMI — prepares the reply and waits for your approval",
        "Daily cap: 10 → 3",
        "Cc, before: (none)", "Cc, after:", "  • luca.verdi@example.com",
        "Instruction, before:", BLOCK + "short", "Instruction, after:", BLOCK + "longer",
        "Senders:", "  • mario.rossi@example.com", "  • anna.bianchi@example.com"]


@pytest.mark.parametrize("lang,expected", [
    ("en", {"resume": "Resume SEMI rule (first contact AUTO) for mario.rossi@example.com (rule_1)",
            "renew": "Renew SEMI rule (first contact AUTO) for mario.rossi@example.com "
                     "for 30 days (rule_1)",
            "delete": "Delete SEMI rule (first contact AUTO) for mario.rossi@example.com (rule_1)"}),
    ("it", {"resume": "Riattiva regola SEMI (primo contatto AUTO) per mario.rossi@example.com "
                      "(rule_1)",
            "renew": "Rinnova regola SEMI (primo contatto AUTO) per mario.rossi@example.com "
                     "per 30 giorni (rule_1)",
            "delete": "Elimina regola SEMI (primo contatto AUTO) per mario.rossi@example.com "
                      "(rule_1)"}),
])
def test_a_semi_rule_that_sends_to_new_senders_says_so_in_every_title(monkeypatch, lang,
                                                                      expected):
    monkeypatch.setattr(policy, "user_lang", lambda: lang)
    rule = dict(FULL_RULE, rule_id="rule_1", mode="semi", first_contact="auto")
    for action, title in expected.items():
        assert rule_requests.preview(action, rule)["subject"] == title


def test_windows_line_endings_become_newlines():
    assert rule_requests.normalize_instruction("a\r\nb\rc\n") == "a\nb\nc\n"
    assert rule_requests.normalize_instruction(None) is None
    rule_requests.check_agent_limits(
        {"reply_style": rule_requests.normalize_instruction("Reply.\r\nThanks.")})


def test_a_document_path_too_long_to_show_says_so():
    path = "C:/Users/mario/Documents/" + "d" * 220 + ".pdf"
    with pytest.raises(ValueError, match="resolved path of a document is too long") as info:
        rule_requests.check_agent_limits({"doc_paths": [path]})
    assert str(rule_requests._VALUE_MAX) in str(info.value)


def test_a_separator_in_a_one_line_value_is_marked_not_turned_into_a_space():
    shown = rule_requests._one("ab c d")
    assert shown == "a�b�c d"
