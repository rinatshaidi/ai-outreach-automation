#!/usr/bin/env python3
"""Prepare an auditable B2B outreach CSV without sending email.

The script validates the relation between a company website and its contact
email. In offline mode it adds audit columns only. With --llm it may retrieve
public text from source_url and ask an OpenAI-compatible API for a short
personalization draft. A mismatched email domain is never auto-personalized.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REQUIRED_FIELDS = {"company", "website", "email"}
ADDED_FIELDS = ("personalization", "source_url", "audit_status", "audit_details", "error")
MAX_SOURCE_CHARS = 8_000
USER_AGENT = "ai-outreach-automation/0.1 (public research only)"


@dataclass(frozen=True)
class AuditResult:
    status: str
    details: str


class VisibleTextParser(HTMLParser):
    """Extract visible text without third-party dependencies."""

    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return " ".join(self._parts)[:MAX_SOURCE_CHARS]


def normalized_host(value: str) -> str:
    """Return the lower-case host from a URL or a host-like string."""
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    return host.rstrip(".")


def domain_hint(host: str) -> str:
    """Conservative two-label domain comparison; not a public-suffix parser."""
    labels = [label for label in host.split(".") if label]
    return ".".join(labels[-2:]) if len(labels) > 1 else host


def audit_email_domain(email: str, website: str) -> AuditResult:
    if "@" not in email:
        return AuditResult("invalid_email", "Email does not contain @.")
    website_host = normalized_host(website)
    if not website_host:
        return AuditResult("missing_website", "Website is missing.")
    email_host = normalized_host(email.rsplit("@", 1)[1])
    if email_host == website_host or email_host.endswith(f".{website_host}"):
        return AuditResult("matched", "Email domain matches the website domain.")
    if domain_hint(email_host) == domain_hint(website_host):
        return AuditResult("matched", "Email and website share a domain hint.")
    return AuditResult(
        "domain_mismatch",
        f"Email domain {email_host} differs from website domain {website_host}; review required.",
    )


def fetch_public_text(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - URL supplied by user
        if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("Source is not an HTML page.")
        html = response.read(1_000_000).decode(
            response.headers.get_content_charset() or "utf-8", errors="replace"
        )
    parser = VisibleTextParser()
    parser.feed(html)
    return parser.get_text()


def generate_personalization(
    *, company: str, source_url: str, source_text: str, timeout: int
) -> str:
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    if not api_key or not model:
        raise RuntimeError("Set LLM_API_KEY and LLM_MODEL before using --llm.")

    prompt = (
        "Write a Russian B2B cold-email personalization for the company below. "
        "Use only the supplied source text. Return 1-2 sentences, no more than 45 words. "
        "If the source lacks a specific fact, return exactly: INSUFFICIENT_EVIDENCE.\n\n"
        f"Company: {company}\nSource: {source_url}\nSource text:\n{source_text}"
    )
    payload = json.dumps(
        {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "Do not invent facts or companies."},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - configured endpoint
        body = json.loads(response.read().decode("utf-8"))
    result = body["choices"][0]["message"]["content"].strip()
    if len(result.split()) > 45:
        raise ValueError("LLM response exceeds 45 words.")
    return result


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row.")
        missing = REQUIRED_FIELDS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
        return list(reader), list(reader.fieldnames)


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def enrich(input_path: Path, output_path: Path, *, use_llm: bool, timeout: int) -> None:
    rows, fields = read_csv(input_path)
    output_fields = fields + [field for field in ADDED_FIELDS if field not in fields]

    for row in rows:
        audit = audit_email_domain(row["email"], row["website"])
        row["audit_status"] = audit.status
        row["audit_details"] = audit.details
        row["error"] = ""
        row["source_url"] = row.get("source_url") or row["website"]

        if audit.status == "domain_mismatch":
            row["error"] = "Personalization skipped until domain mismatch is reviewed."
            continue
        if use_llm and not row.get("personalization", "").strip():
            try:
                source_text = fetch_public_text(row["source_url"], timeout)
                row["personalization"] = generate_personalization(
                    company=row["company"],
                    source_url=row["source_url"],
                    source_text=source_text,
                    timeout=timeout,
                )
            except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as error:
                row["error"] = f"{type(error).__name__}: {error}"

    write_csv(output_path, rows, output_fields)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 CSV with company, website, email.")
    parser.add_argument("--output", required=True, type=Path, help="Destination UTF-8 CSV.")
    parser.add_argument("--llm", action="store_true", help="Create empty personalization drafts via LLM.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        enrich(args.input, args.output, use_llm=args.llm, timeout=max(1, args.timeout))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
