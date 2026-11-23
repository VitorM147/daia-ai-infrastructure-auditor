"""Local sensitive-data detection and masking.

Runs BEFORE any text reaches an AI model or a report. Findings carry only the
category and count, never the raw value. Not a replacement for Sensitive Data
Scanner (a separate billable product) and never activates it.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_\.=]{16,}")),
    ("secret_assignment", re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization)\b\s*[=:]\s*[^\s,;\"']{4,}")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}\b")),
    ("cnpj", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")),
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
]
_CARD_RX = re.compile(r"\b(?:\d[ \-]?){13,19}\b")
_CPF_PLAIN_RX = re.compile(r"(?<!\d)\d{11}(?!\d)")


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def cpf_ok(digits: str) -> bool:
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(digits[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(digits[n]):
            return False
    return True


@dataclass(frozen=True)
class MaskResult:
    text: str
    findings: dict[str, int]

    @property
    def has_sensitive(self) -> bool:
        return bool(self.findings)


def mask(text: str) -> MaskResult:
    found: Counter[str] = Counter()
    out = text or ""
    for name, rx in _RULES:
        def repl(m, _n=name):
            found[_n] += 1
            if _n == "secret_assignment":
                return f"{m.group(1)}=[MASKED:{_n}]"
            return f"[MASKED:{_n}]"
        out = rx.sub(repl, out)

    def card(m):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            found["payment_card"] += 1
            return "[MASKED:payment_card]"
        return m.group(0)
    out = _CARD_RX.sub(card, out)

    def cpf(m):
        if cpf_ok(m.group(0)):
            found["cpf"] += 1
            return "[MASKED:cpf]"
        return m.group(0)
    out = _CPF_PLAIN_RX.sub(cpf, out)
    return MaskResult(out, dict(found))


def mask_all(messages: list[str]) -> tuple[list[str], dict[str, int]]:
    total: Counter[str] = Counter()
    masked = []
    for m in messages:
        r = mask(m)
        masked.append(r.text)
        total.update(r.findings)
    return masked, dict(total)
