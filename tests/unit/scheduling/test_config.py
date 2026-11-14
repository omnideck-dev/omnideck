"""Preserve installed user limits when moving them out of routine config."""
from config import AppConfig, load_config


def test_existing_routine_limits_migrate_without_overriding_explicit_scheduler_settings():
    data = load_config().model_dump()
    data.pop('scheduling')
    data['routines'].update(max_concurrent=7, poll_interval=3, shutdown_timeout=9)
    migrated = AppConfig.model_validate(data)
    assert migrated.scheduling.model_dump() == {'max_concurrent': 7, 'poll_interval': 3, 'shutdown_timeout': 9}
    assert 'max_concurrent' not in migrated.routines.model_dump()
    data['scheduling'] = {'max_concurrent': 4}
    assert AppConfig.model_validate(data).scheduling.max_concurrent == 4
    assert data['routines']['max_concurrent'] == 7  # Validation must not mutate input.
