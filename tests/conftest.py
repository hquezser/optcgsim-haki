import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def autosaved_log() -> str:
    return (FIXTURES / "match_autosaved.log").read_text()


@pytest.fixture
def player_log_lines() -> list[str]:
    return (FIXTURES / "session_player.log").read_text().splitlines()


@pytest.fixture
def truncated_log() -> str:
    """Log coupé avant la ligne 'Wins!' : l'adversaire est à 0 vie sous l'assaut final."""
    return (FIXTURES / "match_truncated.log").read_text()
