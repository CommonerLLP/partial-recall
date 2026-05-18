"""Log-sanitization processor.

structlog processor that strips three classes of secret/PII from log
records before they hit any renderer:

  1. **Sensitive field VALUES** — any key whose name matches a sensitive
     pattern (api_key, token, secret, password, authorization, etc.).
     Value is replaced with ``"***"`` regardless of type/length.

  2. **Sensitive value SHAPES** — even if the field name is innocent,
     values that look like an API key / token / JWT / PEM private key
     are redacted in-place. Defence-in-depth: a developer who logs an
     API key in a field called ``extra_context`` shouldn't ship it.

  3. **Absolute filesystem paths** — any string field containing an
     absolute POSIX or Windows path is normalised: home directory →
     ``~``; system paths kept as-is (those don't leak who the user is).

These two together cover the documented public/private firewall risk
classes for partial-recall:

  * Gemini API keys (and any future provider keys).
  * Filesystem paths that identify the user or their corpus location
    (e.g. ``/Users/aakash/Zotero/zotero.sqlite``).

Not in scope (deliberate, v0.2.0):

  * Free-text inside ``event`` strings — sanitising message bodies
    requires NLP-grade heuristics. We aim for **never log secrets in
    event strings in the first place**; this processor is the
    defence-in-depth layer.
  * Zotero item_keys — public-ish identifiers, kept.
  * Database row contents — those don't pass through logs.

CI invariant: the test suite passes a representative set of records
through the processor and asserts no key/value of the redaction
classes survives. Adding a new log call site that breaks the invariant
fails CI.
"""

from __future__ import annotations

import os
import re
from typing import Any

_SENSITIVE_KEY_PATTERNS = re.compile(
    r"""
    (^|_|\.)            # word boundary at start or via underscore/dot
    (
        api[_-]?key
      | apikey
      | secret
      | token
      | password
      | passwd
      | authorization
      | auth[_-]?token
      | bearer
      | private[_-]?key
      | session[_-]?id
      | cookie
    )
    ($|_|\.)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_REDACTED = "***"

# Detect absolute paths. We're conservative: full-string-or-substring
# match for /Users/<user>/, /home/<user>/, and C:\Users\<user>\ shapes.
# Matching on substring (not full-string) lets us catch paths embedded
# in longer messages like "opened /Users/aakash/Zotero/zotero.sqlite".
_HOME_DIR_RE = re.compile(
    r"""
    (
        /Users/[^/\s]+
      | /home/[^/\s]+
      | [A-Za-z]:\\Users\\[^\\\s]+
    )
    """,
    re.VERBOSE,
)


# Value-shape patterns: redact even when the field name itself isn't
# sensitive. Defence-in-depth — a developer who logs an API key in a
# field called "wow_look_at_this" still shouldn't ship it.
#
# Each entry is (compiled_regex, label_for_debug). Patterns are
# deliberately strict so they don't accidentally redact innocent
# alphanumeric strings.
_VALUE_SHAPE_PATTERNS = [
    # Gemini / Google Cloud API keys: AIzaSy + 33 chars (39 total).
    (re.compile(r"AIzaSy[A-Za-z0-9_\-]{30,}"), "gemini-api-key"),
    # GitHub fine-grained / classic tokens: ghp_, gho_, ghu_, ghs_, ghr_.
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "github-token"),
    # OpenAI keys: sk-…  (legacy + new sk-proj- shapes; conservative ≥20 chars).
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}\b"), "openai-key"),
    # Generic bearer JWTs (eyJ… three dot-separated base64-url chunks).
    (re.compile(
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
    ), "jwt"),
    # PEM-wrapped private keys (catch the header; anything after is collateral).
    (re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----[\s\S]*?-----END[ A-Z]*PRIVATE KEY-----"),
     "pem-private-key"),
    # Bare PEM header (e.g. truncated value, common in logs).
    (re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----"), "pem-private-key-header"),
]


def _redact_value_shapes(value: str) -> str:
    """Redact substrings that look like a secret regardless of field name."""
    for pattern, _label in _VALUE_SHAPE_PATTERNS:
        value = pattern.sub(_REDACTED, value)
    return value


def _redact_home_paths(value: str) -> str:
    """Replace any /Users/<user> or /home/<user> prefix with ~."""
    return _HOME_DIR_RE.sub("~", value)


def _is_sensitive_key(key: str) -> bool:
    if not isinstance(key, str):
        return False
    return bool(_SENSITIVE_KEY_PATTERNS.search(key))


def sanitize_event_dict(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: redact sensitive fields and home paths in place.

    Returns the same dict object (structlog convention). Safe on
    arbitrary input — does not raise on unexpected value types.
    """
    for key, value in list(event_dict.items()):
        if _is_sensitive_key(key):
            event_dict[key] = _REDACTED
            continue
        if isinstance(value, str):
            # Order matters: catch the secret-shape FIRST (it may be
            # embedded in a longer string), then normalise home paths.
            cleaned = _redact_value_shapes(value)
            cleaned = _redact_home_paths(cleaned)
            event_dict[key] = cleaned
        elif isinstance(value, os.PathLike):
            event_dict[key] = _redact_home_paths(os.fspath(value))
    return event_dict
