import zipfile

from researchguard.security_check import (
    check_ignores,
    check_local_binding,
    check_secrets,
    check_wheel,
)


def test_secret_scan_reports_filename_without_secret_value(tmp_path):
    value = "sk-" + "a" * 24
    suspect = tmp_path / "notes.txt"
    suspect.write_text(f"token={value}", encoding="utf-8")
    result = check_secrets(tmp_path)
    assert result.status == "FAIL"
    assert "notes.txt" in result.detail
    assert value not in result.detail


def test_local_configuration_checks(tmp_path):
    (tmp_path / ".gitignore").write_text(
        ".env\n.certs/\n.venv/\nresearchguard.db\n*.db-shm\n*.db-wal\ndist/\ntest-results/\n",
        encoding="utf-8",
    )
    api = tmp_path / "src/researchguard/api.py"
    api.parent.mkdir(parents=True)
    api.write_text('uvicorn.run("app", host="127.0.0.1")', encoding="utf-8")
    assert check_ignores(tmp_path).status == "PASS"
    assert check_local_binding(tmp_path).status == "PASS"


def test_secret_scan_skips_ignored_local_certificate_directory(tmp_path):
    certificates = tmp_path / ".certs"
    certificates.mkdir()
    private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
    (certificates / "localhost-key.pem").write_text(
        f"{private_key_marker}\nlocal-only\n-----END PRIVATE KEY-----",
        encoding="utf-8",
    )
    assert check_secrets(tmp_path).status == "PASS"


def test_package_check_rejects_sensitive_files(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "researchguard-test.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("researchguard/web/index.html", "ok")
        archive.writestr("researchguard/.env", "secret")
    result = check_wheel(tmp_path)
    assert result.status == "FAIL"
    assert "researchguard/.env" in result.detail
