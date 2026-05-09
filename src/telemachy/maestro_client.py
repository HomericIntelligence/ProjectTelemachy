"""DEPRECATED: Use agamemnon_client instead.

This module is kept for backward compatibility. All symbols are re-exported
from agamemnon_client.

.. deprecated::
    Scheduled for removal in v1.0.0. Update all imports to use
    ``telemachy.agamemnon_client`` directly.
"""

from telemachy.agamemnon_client import AgamemnonClient as AgamemnonClient
from telemachy.agamemnon_client import AgamemnonClient as MaestroClient  # backward compat
from telemachy.agamemnon_client import AgamemnonError as AgamemnonError
from telemachy.agamemnon_client import AgamemnonError as MaestroError  # backward compat

__all__ = ["AgamemnonClient", "AgamemnonError", "MaestroClient", "MaestroError"]
