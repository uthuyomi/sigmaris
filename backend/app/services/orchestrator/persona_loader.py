from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass(frozen=True)
class PersonaDocument:
    content: str
    sha256: str
    version: str
    path: str


# Module-level mtime cache — reload only when file changes on disk.
_cached_persona: PersonaDocument | None = None
_cached_persona_mtime: float = -1.0
_cached_persona_path: str = ""


def load_persona() -> PersonaDocument:
    global _cached_persona, _cached_persona_mtime, _cached_persona_path

    configured_path = Path(settings.sigmaris_persona_path).expanduser()
    candidates = [
        configured_path,
        Path(__file__).resolve().parents[4] / "docs" / "persona.md",
        Path("/app/docs/persona.md"),
    ]
    path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if path is None:
        checked = ", ".join(str(candidate) for candidate in candidates)
        raise RuntimeError(f"Unable to locate Sigmaris persona. Checked: {checked}")

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0

    if (
        _cached_persona is not None
        and _cached_persona_path == str(path)
        and _cached_persona_mtime == mtime
    ):
        return _cached_persona

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"Unable to load Sigmaris persona as UTF-8: {path}") from error

    if not content.strip():
        raise RuntimeError(f"Sigmaris persona is empty: {path}")

    first_line = content.splitlines()[0].strip()
    version = first_line.removeprefix("#").strip() or "unknown"
    doc = PersonaDocument(
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        version=version,
        path=str(path),
    )

    _cached_persona = doc
    _cached_persona_mtime = mtime
    _cached_persona_path = str(path)
    return doc
