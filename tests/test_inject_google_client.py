"""The build-time injection of the Google OAuth client.

google_config.json is committed empty; the release workflow fills it from
two repository secrets with scripts/inject_google_client.py. These tests
pin the contract that matters: the pair is written whole or not at all,
the release fails loudly when it is missing, and the secret never reaches
the job log.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inject_google_client.py"
_spec = importlib.util.spec_from_file_location("inject_google_client", _SCRIPT)
inject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject)

CLIENT_ID = "123-abc.apps.googleusercontent.com"
# Ends with "example" on purpose: the plugin security scanner reads a bare
# `SECRET = "..."` as a hardcoded secret unless the value is a recognised
# placeholder, and the injector only checks the GOCSPX- prefix.
SECRET = "GOCSPX-value-example"


@pytest.fixture()
def config(tmp_path):
    p = tmp_path / "google_config.json"
    p.write_text(json.dumps({"client_id": "", "client_secret": "",
                             "_note": "kept as is"}), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)


def test_writes_the_pair_and_keeps_the_other_keys(config, monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", SECRET)

    assert inject.main([str(config)]) == 0

    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["client_id"] == CLIENT_ID
    assert written["client_secret"] == SECRET
    assert written["_note"] == "kept as is"


def test_the_secret_never_reaches_the_log(config, monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", SECRET)

    inject.main([str(config)])

    out = capsys.readouterr().out
    assert SECRET not in out
    assert CLIENT_ID in out, "the id is public and useful to see in the log"


def test_missing_secrets_fail_the_build_and_leave_the_file_alone(config, capsys):
    before = config.read_text(encoding="utf-8")

    assert inject.main([str(config)]) == 1

    assert config.read_text(encoding="utf-8") == before
    assert "::error::" in capsys.readouterr().out


def test_half_a_pair_is_refused(config, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", CLIENT_ID)

    assert inject.main([str(config)]) == 1
    assert json.loads(config.read_text(encoding="utf-8"))["client_id"] == ""


def test_swapped_values_are_refused(config, monkeypatch, capsys):
    """The two secrets look nothing alike; pasting them into the wrong
    fields must stop the release, not ship an unusable client."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", SECRET)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", CLIENT_ID)

    assert inject.main([str(config)]) == 1
    assert "swapped" in capsys.readouterr().out


def test_default_target_is_the_shipped_config():
    assert inject.DEFAULT_PATH.name == "google_config.json"
    assert inject.DEFAULT_PATH.parent.name == "core"
    assert inject.DEFAULT_PATH.exists(), "the shipped file must exist, empty, in git"
