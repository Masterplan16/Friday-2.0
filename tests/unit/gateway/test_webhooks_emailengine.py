"""
Tests unitaires pour webhook EmailEngine
Story 2.1 - Subtask 6.1

OBSOLETE (D25, 2026-02-13): EmailEngine retiré, remplacé par IMAP direct (aioimaplib).
Ces tests sont conservés pour référence historique mais tous les tests sont skippés.

Pour les nouveaux tests IMAP, voir:
- tests/integration/test_imap_fetcher.py (à créer si nécessaire)
"""

import pytest

# Skip all tests in this module (EmailEngine retired D25)
pytestmark = pytest.mark.skip(reason="EmailEngine retired (D25), replaced by IMAP direct")


def test_placeholder():
    """Placeholder test (skipped)."""
    pass
