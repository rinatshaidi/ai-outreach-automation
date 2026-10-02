"""Semantic guardrails for owner-facing public contact routes."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def is_relevant_official_path(url: str, anchor: str = "") -> bool:
    """Return true only for a real contact, careers or partnership path."""

    del anchor  # Kept for compatible callers; destination semantics win.
    path = urlparse(url).path.casefold()
    tokens = set(re.findall(r"[a-z0-9]+", path))
    if tokens.intersection({"blog", "news", "article", "insights", "resources", "press"}):
        return False
    return bool(
        tokens.intersection(
            {
                "contact", "contacts", "apply", "application", "career", "careers",
                "job", "jobs", "recruit", "recruitment", "hiring", "partner", "partners",
                "partnership", "partnerships", "business", "sales",
            }
        )
    )


def is_semantic_contact_channel(channel_type: str, url: str | None) -> bool:
    """Check that an owner-facing channel matches its declared route type."""

    if channel_type != "official_form":
        return True
    return bool(url and is_relevant_official_path(url))
