"""PII redaction and untrusted-data handling. Runs on EVERYTHING before it reaches the LLM.

Threat model in one paragraph: bank narrations contain other people's names, phone numbers, account
numbers and UPI handles - and they are *attacker-controllable* (anyone who sends you ₹1 chooses the
narration text). So they are (a) personal data we minimize before sending to a third-party API and
(b) untrusted input that may contain prompt injections. See docs/SECURITY.md.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{9,18}(?!\d)")                 # account numbers, UPI refs
_CARD = re.compile(r"(?<![\d-])(?:\d{4}[ -]){3}\d{4}(?![\d-])")       # spaced/dashed 16-digit cards
# person-like VPA local parts (contain a dot or digits): rahul.sharma@okaxis, 98xxxx@ybl
_VPA_PERSON = re.compile(r"\b([a-z0-9]*[.\d][a-z0-9._-]*)@([a-z]+)\b", re.I)

_INJECTION = re.compile(
    r"(ignore (all |the )?(previous|prior|above)|disregard .*instructions|system prompt|you are now|"
    r"\bassistant\s*:|\bsystem\s*:|categori[sz]e (this|it|me) as|<\s*/?\s*(system|instructions?)\s*>)",
    re.I,
)


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _VPA_PERSON.sub(lambda m: f"[vpa]@{m.group(2)}", text)
    text = _PHONE.sub("[phone]", text)
    text = _CARD.sub(lambda m: "[card-" + re.sub(r"\D", "", m.group(0))[-4:] + "]", text)
    text = _LONG_DIGITS.sub(lambda m: "[num-" + m.group(0)[-4:] + "]", text)
    return text


def looks_like_injection(text: str) -> bool:
    """Heuristic tripwire. It does NOT make injection impossible (constrained outputs do most of that);
    it routes suspicious rows to a human instead of trusting the model's verdict on them."""
    return bool(_INJECTION.search(text))


def sanitize_untrusted(text: str, max_chars: int = 200) -> str:
    """Strip control chars / markup delimiters we use in prompts, cap length."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
    text = text.replace("<", "‹").replace(">", "›")
    return text[:max_chars]
