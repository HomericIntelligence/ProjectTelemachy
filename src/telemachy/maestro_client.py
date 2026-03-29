"""DEPRECATED: Use agamemnon_client instead.

This module is kept for backward compatibility. All symbols are re-exported
from agamemnon_client. Will be removed in a future release.
"""

from telemachy.agamemnon_client import AgamemnonClient as AgamemnonClient
from telemachy.agamemnon_client import AgamemnonClient as MaestroClient  # backward compat
from telemachy.agamemnon_client import AgamemnonError as AgamemnonError
from telemachy.agamemnon_client import AgamemnonError as MaestroError  # backward compat

__all__ = ["AgamemnonClient", "AgamemnonError", "MaestroClient", "MaestroError"]
