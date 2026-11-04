"""Test the isolated Codespace QA environment without Docker or network calls."""

import pytest


def test_beta_qa_secrets_are_private_and_provider_free(tmp_path):
    """Preparing QA must not copy live tokens or overwrite its own database key."""
    from scripts.beta_qa_environment import prepare_environment

    target = tmp_path / "qa.env"
    prepare_environment(target)
    original = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert b"POSTGRES_DB=shop_codespace\n" in original
    assert b"SHOP_BETA_QA=1\n" in original
    assert b"TOKEN=\n" in original
    prepare_environment(target)
    assert target.read_bytes() == original


def test_existing_unknown_environment_is_not_replaced(tmp_path):
    """An unrelated environment must never become a reset target."""
    from scripts.beta_qa_environment import prepare_environment

    target = tmp_path / "qa.env"
    target.write_text("POSTGRES_DB=production\n")
    with pytest.raises(RuntimeError):
        prepare_environment(target)
    assert target.read_text() == "POSTGRES_DB=production\n"


@pytest.mark.parametrize("override", [None, ("TOKEN", "live-token"), ("POSTGRES_DB", "production"), ("SHOP_BROADCAST_WORKER_ENABLED", "true")])
def test_beta_lab_guard_requires_exact_identity_and_inert_providers(tmp_path, monkeypatch, override):
    """A named QA database alone never authorizes provider or worker traffic."""
    from scripts.beta_qa_environment import prepare_environment
    from scripts.test_lab_safety import require_isolated_lab

    target = prepare_environment(tmp_path / "qa.env")
    for line in target.read_text().splitlines():
        key, value = line.split("=", 1)
        monkeypatch.setenv(key, value)
    if override is None:
        require_isolated_lab()
    else:
        monkeypatch.setenv(*override)
        with pytest.raises(RuntimeError):
            require_isolated_lab()
