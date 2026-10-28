"""Check the bundled LGPL library's source notice and locked version."""

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_zeroconf_notice_matches_locked_runtime() -> None:
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    match = re.search(
        r'\[\[package\]\]\s*\nname = "zeroconf"\s*\nversion = "([^"]+)"',
        lock,
    )
    assert match is not None
    notice = (REPO_ROOT / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    assert f"zeroconf {match.group(1)}" in notice
    assert "LGPL-2.1-or-later" in notice
    assert "third_party/licenses/zeroconf-COPYING" in notice


def test_zeroconf_copying_has_original_copyright_and_lgpl() -> None:
    license_text = (
        REPO_ROOT / "third_party" / "licenses" / "zeroconf-COPYING"
    ).read_text(encoding="utf-8")
    assert license_text.startswith("python-zeroconf is distributed under the GNU Lesser")
    assert "Copyright 2020-2026 J. Nick Koston" in license_text
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
