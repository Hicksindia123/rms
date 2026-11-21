"""Print branding shared by the slip PDFs (DEC-65 / Q26).

The logo drawn on a slip PDF is configuration: system setting `branding_print_logo` names an
image shipped with the backend in `app/assets/branding` (the repo-root `PNG LOGO HICKS.png` is
shipped as `hicks-logo.png`). Only a bare file name inside that folder is accepted, so a setting
can never point the renderer at another file. An empty value means "no logo": the slip prints the
company name only.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger("rms.branding")

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "branding"
LOGO_SETTING = "branding_print_logo"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.(png|jpg|jpeg)$")


@lru_cache(maxsize=8)
def _read_asset(name: str) -> bytes:
    return (ASSETS_DIR / name).read_bytes()


def print_logo(session: Session) -> bytes | None:
    """Logo bytes for a slip whose template has `show_logo` on, or None (no logo configured).

    A misconfigured setting (unknown file, unsafe name) is logged and the slip prints without the
    logo: a slip must still be printable, and the setting is fixed in Admin → Settings.
    """
    value: Any = session.execute(
        text("select value from public.system_settings where key = :key"), {"key": LOGO_SETTING}
    ).scalar()
    name = value.strip() if isinstance(value, str) else ""
    if not name:
        return None
    if not _SAFE_NAME.fullmatch(name):
        log.warning("print_logo_invalid_name", setting=LOGO_SETTING, value=name)
        return None
    try:
        return _read_asset(name)
    except FileNotFoundError:
        log.warning("print_logo_missing", setting=LOGO_SETTING, value=name, folder=str(ASSETS_DIR))
        return None


def template_logo(session: Session, layout: dict[str, Any]) -> bytes | None:
    """The logo when the published template layout has `show_logo` on (DEC-41: layout = config)."""
    return print_logo(session) if bool(layout.get("show_logo")) else None
