import common


def test_load_env_parses_and_ignores_junk(tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text(
        "# комментарий\nAPIFY_TOKEN=abc123\nTELEGRAM_CHAT_ID='42'\n\nмусор без равно\n",
        encoding="utf-8",
    )
    env = common.load_env(envfile)
    assert env == {"APIFY_TOKEN": "abc123", "TELEGRAM_CHAT_ID": "42"}


def test_load_env_missing_file(tmp_path):
    assert common.load_env(tmp_path / "nope") == {}


def test_load_config_merges_defaults(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"accounts": ["someblog"], "pulse_multiplier": 3}', encoding="utf-8")
    cfg = common.load_config(cfg_file)
    assert cfg["accounts"] == ["someblog"]
    assert cfg["pulse_multiplier"] == 3
    assert cfg["median_window_days"] == 30  # дефолт
