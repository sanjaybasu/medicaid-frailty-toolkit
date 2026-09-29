"""Guard rails: no member identifiers, no data files, no secrets in the repository."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DATA = {"codes.csv", "components.csv"}


def _files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        files = [ROOT / f for f in out.splitlines()]
        if files:
            return files
    except Exception:
        pass
    def skip(p):
        rel = p.relative_to(ROOT).parts
        return any(x.startswith(".") and x != ".github" for x in rel) or "__pycache__" in rel \
            or any(x.endswith(".egg-info") for x in rel)
    return [p for p in ROOT.rglob("*") if p.is_file() and not skip(p)]


def test_no_member_identifiers():
    pat = re.compile(r"WAY\d{3,}")
    for f in _files():
        if f.suffix in {".svg", ".png"} or not f.exists():
            continue
        assert not pat.search(f.read_text(errors="ignore")), f


def test_no_data_files():
    for f in _files():
        if f.suffix in {".parquet", ".xlsx", ".xls", ".sas7bdat", ".dta", ".feather", ".pkl", ".zip"}:
            raise AssertionError(f)
        if f.suffix == ".csv":
            assert f.name in ALLOWED_DATA, f


def test_no_secrets():
    pat = re.compile(r"(hvs\.[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{30,})")
    for f in _files():
        if f.exists() and f.suffix not in {".svg"}:
            assert not pat.search(f.read_text(errors="ignore")), f
