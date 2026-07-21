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


def test_load_config_legacy_flat_becomes_instagram_section(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"accounts": ["someblog"], "source": "apify"}', encoding="utf-8")
    cfg = common.load_config(cfg_file)
    assert cfg["instagram"] == {"source": "apify", "accounts": ["someblog"]}
    assert cfg["telegram"] is None


def test_load_config_new_format_sections(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        '{"instagram": {"source": "apify", "accounts": ["a"]},'
        ' "telegram": {"source": "web", "channels": ["ch"]}}', encoding="utf-8")
    cfg = common.load_config(cfg_file)
    assert cfg["instagram"]["accounts"] == ["a"]
    assert cfg["telegram"]["channels"] == ["ch"]


def test_active_accounts_pairs_and_lowercase():
    cfg = dict(common.DEFAULTS,
               instagram={"source": "apify", "accounts": ["NatGeo"]},
               telegram={"source": "web", "channels": ["SoloKumi"]})
    assert common.active_accounts(cfg) == [
        ("instagram", "natgeo"), ("telegram", "solokumi")]


def test_active_accounts_empty_platforms():
    assert common.active_accounts(dict(common.DEFAULTS)) == []
