"""The shipped config gives each scheduled source its own run limit."""
from config import load_config


def test_shipped_config_loads_both_run_limits():
    assert load_config().scheduling.max_concurrent == {'routines': 4, 'goals': 4}
