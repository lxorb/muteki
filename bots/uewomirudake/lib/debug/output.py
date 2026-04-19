"""
Debug-only prints. Flip the *_ENABLED flags to toggle output:

- dprint: general-purpose debug output (DPRINT_ENABLED).
- tprint: timing/stopwatch output, used by RoundStopwatch (TPRINT_ENABLED).

Bindings are resolved once at import time so each call site jumps
directly to either the builtin print or a no-op with no per-call
branch / attribute lookup / flag check.
"""

DPRINT_ENABLED: bool = False
TPRINT_ENABLED: bool = True


def _noop(*_args, **_kwargs) -> None:
    return None


dprint = print if DPRINT_ENABLED else _noop
tprint = print if TPRINT_ENABLED else _noop
