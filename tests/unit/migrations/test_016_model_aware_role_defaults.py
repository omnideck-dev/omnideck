import json

import pytest

from migrations._016_model_aware_role_defaults import migrate


@pytest.mark.unit
def test_clears_only_untouched_legacy_role_options(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({
        "vision_options": {
            "num_ctx": 60000,
            "num_predict": 512,
            "temperature": 0.3,
            "top_k": 20,
        },
        "compaction_options": {"temperature": 0.1},
    }))

    migrate(tmp_path)

    saved = json.loads(settings_path.read_text())
    assert saved["vision_options"] == {}
    assert saved["compaction_options"] == {"temperature": 0.1}
