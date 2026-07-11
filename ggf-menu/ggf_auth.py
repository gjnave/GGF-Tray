"""Compatibility import for older GGF Tray integrations.

The maintained implementation lives in ggf_auth_token.py.  Keeping this tiny
shim prevents two authentication implementations from drifting apart.
"""

from ggf_auth_token import AuthManager

__all__ = ["AuthManager"]
