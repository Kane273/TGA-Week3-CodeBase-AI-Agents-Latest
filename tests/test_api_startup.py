from pathlib import Path

import pytest

from researchguard import api


def test_https_requires_certificate_and_key(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RESEARCHGUARD_SSL_CERTFILE", str(tmp_path / "localhost.pem"))
    monkeypatch.delenv("RESEARCHGUARD_SSL_KEYFILE", raising=False)
    with pytest.raises(SystemExit, match="Set both"):
        api.main()


def test_https_rejects_missing_files(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RESEARCHGUARD_SSL_CERTFILE", str(tmp_path / "localhost.pem"))
    monkeypatch.setenv("RESEARCHGUARD_SSL_KEYFILE", str(tmp_path / "localhost-key.pem"))
    with pytest.raises(SystemExit, match="does not exist"):
        api.main()
