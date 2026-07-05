from __future__ import annotations

from types import SimpleNamespace

from stockmonitor.config import load_config, merge_config_into_args


def test_load_config_reads_explicit_toml_path(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[common]
loop = 60

[casto]
postcode = "75011"
radius_km = 15
""",
        encoding="utf-8",
    )

    assert load_config(config_path) == {
        "common": {"loop": 60},
        "casto": {"postcode": "75011", "radius_km": 15},
    }


def test_load_config_returns_empty_for_missing_or_invalid_file(tmp_path):
    assert load_config(tmp_path / "missing.toml") == {}

    invalid = tmp_path / "invalid.toml"
    invalid.write_text("[common\n", encoding="utf-8")
    assert load_config(invalid) == {}


def test_merge_config_into_args_preserves_cli_values_and_merges_common_then_retailer():
    args = SimpleNamespace(loop=10, data_dir=None, notify_cmd=None)
    cfg = {
        "common": {
            "loop": 900,
            "data_dir": "data",
            "notify_cmd": "common-notify",
            "ignored_none": None,
        },
        "casto": {
            "notify_cmd": "casto-notify",
            "postcode": "75011",
            "radius_km": 15,
        },
    }

    merge_config_into_args(args, cfg, "casto")

    assert args.loop == 10
    assert args.data_dir == "data"
    assert args.notify_cmd == "casto-notify"
    assert args.postcode == "75011"
    assert args.radius_km == 15
    assert not hasattr(args, "ignored_none")
