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


def load_persona() -> PersonaDocument:
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
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"Unable to load Sigmaris persona as UTF-8: {path}") from error

    if not content.strip():
        raise RuntimeError(f"Sigmaris persona is empty: {path}")

    first_line = content.splitlines()[0].strip()
    version = first_line.removeprefix("#").strip() or "unknown"
    return PersonaDocument(
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        version=version,
        path=str(path),
    )
