from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

SKIP_PARTS = {
    ".git",
    ".certs",
    ".venv",
    "node_modules",
    "dist",
    "test-results",
    "playwright-report",
    "__pycache__",
}
SECRET_PATTERNS = {
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
REQUIRED_IGNORES = {
    ".env",
    ".certs/",
    ".venv/",
    "researchguard.db",
    "*.db-shm",
    "*.db-wal",
    "dist/",
    "test-results/",
}


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name == ".env" or path.stat().st_size > 2_000_000:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def check_secrets(root: Path) -> CheckResult:
    findings: list[str] = []
    for path, content in _text_files(root):
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{path.relative_to(root)} ({label})")
    if findings:
        return CheckResult("Credential scan", "FAIL", ", ".join(findings))
    return CheckResult("Credential scan", "PASS", "No likely API or private keys found")


def check_ignores(root: Path) -> CheckResult:
    ignore_file = root / ".gitignore"
    values = (
        {
            line.strip()
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        if ignore_file.exists()
        else set()
    )
    missing = sorted(REQUIRED_IGNORES - values)
    if missing:
        return CheckResult("Sensitive artifact ignores", "FAIL", f"Missing: {', '.join(missing)}")
    return CheckResult("Sensitive artifact ignores", "PASS", "Local secrets and artifacts ignored")


def check_git(root: Path) -> CheckResult:
    if not (root / ".git").exists():
        return CheckResult("Git tracking", "WARN", "No repository here; history scan unavailable")
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            ".env",
            ".env.*",
            "*.db",
            "*.db-shm",
            "*.db-wal",
            ".certs",
            "*.key",
            "*.pem",
            "test-results",
            "playwright-report",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    tracked = [path for path in tracked if path != ".env.example"]
    if tracked:
        return CheckResult("Git tracking", "FAIL", f"Sensitive paths tracked: {', '.join(tracked)}")
    return CheckResult("Git tracking", "PASS", "No sensitive runtime paths tracked")


def check_local_env(root: Path) -> CheckResult:
    if (root / ".env").exists():
        return CheckResult("Local environment file", "WARN", ".env exists; exclude it when sharing")
    return CheckResult("Local environment file", "PASS", "No local .env file present")


def check_local_binding(root: Path) -> CheckResult:
    api = (root / "src/researchguard/api.py").read_text(encoding="utf-8")
    if 'host="127.0.0.1"' not in api:
        return CheckResult("Local server binding", "FAIL", "API does not default to 127.0.0.1")
    return CheckResult("Local server binding", "PASS", "API defaults to loopback only")


def check_wheel(root: Path) -> CheckResult:
    wheels = sorted((root / "dist").glob("*.whl"))
    if not wheels:
        return CheckResult("Package contents", "WARN", "No wheel found; run uv build")
    with zipfile.ZipFile(wheels[-1]) as archive:
        names = archive.namelist()
    forbidden = [name for name in names if name.endswith((".env", ".db"))]
    if forbidden:
        return CheckResult("Package contents", "FAIL", f"Sensitive files packaged: {forbidden}")
    return CheckResult("Package contents", "PASS", f"Checked {wheels[-1].name}")


def _run(command: list[str], root: Path, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=root, capture_output=True, text=True, timeout=timeout, check=False
    )


def check_tests(root: Path) -> CheckResult:
    python = root / ".venv/bin/python"
    executable = str(python) if python.exists() else shutil.which("python") or "python"
    result = _run([executable, "-m", "pytest", "-q"], root)
    if result.returncode:
        return CheckResult("Python tests", "FAIL", "Test suite failed; run pytest for details")
    return CheckResult("Python tests", "PASS", "Test suite passed")


def check_python_audit(root: Path) -> CheckResult:
    local = root / ".venv/bin/pip-audit"
    executable = str(local) if local.exists() else shutil.which("pip-audit")
    if not executable:
        return CheckResult("Python dependency audit", "WARN", "pip-audit not installed")
    result = _run([executable, "--progress-spinner", "off"], root)
    if result.returncode:
        return CheckResult(
            "Python dependency audit", "FAIL", "Vulnerabilities or audit errors found"
        )
    return CheckResult("Python dependency audit", "PASS", "No known vulnerabilities reported")


def check_npm_audit(root: Path) -> CheckResult:
    if not shutil.which("npm") or not (root / "package-lock.json").exists():
        return CheckResult("npm dependency audit", "WARN", "npm or package-lock.json unavailable")
    result = _run(["npm", "audit", "--json", "--audit-level=high"], root)
    try:
        payload = json.loads(result.stdout or "{}")
        counts = payload.get("metadata", {}).get("vulnerabilities", {})
        high = int(counts.get("high", 0)) + int(counts.get("critical", 0))
    except (ValueError, TypeError):
        return CheckResult("npm dependency audit", "WARN", "Audit unavailable, likely offline")
    if high:
        return CheckResult("npm dependency audit", "FAIL", f"{high} high/critical findings")
    if result.returncode and not counts:
        return CheckResult("npm dependency audit", "WARN", "Audit could not complete")
    return CheckResult("npm dependency audit", "PASS", "No high/critical vulnerabilities reported")


def run_security_check(
    root: Path, *, run_tests: bool = True, run_audits: bool = True
) -> list[CheckResult]:
    root = root.resolve()
    results = [
        check_secrets(root),
        check_ignores(root),
        check_git(root),
        check_local_env(root),
        check_local_binding(root),
        check_wheel(root),
    ]
    if run_tests:
        results.append(check_tests(root))
    if run_audits:
        results.extend([check_python_audit(root), check_npm_audit(root)])
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run non-destructive local project checks.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-audits", action="store_true")
    args = parser.parse_args()
    results = run_security_check(
        args.root, run_tests=not args.skip_tests, run_audits=not args.skip_audits
    )
    table = Table(title="ResearchGuard local security check")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    for result in results:
        table.add_row(result.name, f"[{colors[result.status]}]{result.status}[/]", result.detail)
    Console().print(table)
    failures = sum(result.status == "FAIL" for result in results)
    warnings = sum(result.status == "WARN" for result in results)
    Console().print(f"{failures} failure(s), {warnings} warning(s)")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
