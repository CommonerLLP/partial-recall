"""Log-sanitization processor.

structlog processor that strips two classes of secret/PII from log
records before they hit any renderer:

  1. **Sensitive field VALUES** — any key whose name matches a sensitive
     pattern (api_key, token, secret, password, authorization, etc.).
     Value is replaced with ``"***"`` regardless of type/length.

  2. **Absolute filesystem paths** — any string field containing an
     absolute POSIX or Windows path is normalised: home directory →
     ``~``; system paths kept as-is (those don't leak who the user is).

These two together cover the documented public/private firewall risk
classes for partial-recall:

  * Gemini API keys (and any future provider keys).
  * Filesystem paths that identify the user or their corpus location
    (e.g. ``/Users/scholar/Zotero/zotero.sqlite``).

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
# in longer messages like "opened /Users/scholar/Zotero/zotero.sqlite".
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
            event_dict[key] = _redact_home_paths(value)
        elif isinstance(value, os.PathLike):
            event_dict[key] = _redact_home_paths(os.fspath(value))
    return event_dict
