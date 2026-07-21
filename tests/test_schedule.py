import common
import schedule


def test_parse_time():
    assert schedule.parse_time("18:05") == (18, 5)


def test_plist_weekly_has_weekday():
    xml = schedule.plist_xml("com.feedwatch.weekly", "weekly", 18, 0, weekday=0)
    assert "<string>weekly</string>" in xml
    assert "<key>Weekday</key><integer>0</integer>" in xml
    assert "<string>--send</string>" in xml
    assert "report.py" in xml


def test_plist_pulse_no_weekday():
    xml = schedule.plist_xml("com.feedwatch.pulse", "pulse", 10, 0)
    assert "Weekday" not in xml


def test_cron_lines():
    cfg = dict(common.DEFAULTS, weekly_day="sun", weekly_time="18:00", pulse_time="10:30")
    pulse, weekly = schedule.cron_lines(cfg)
    assert pulse.startswith("30 10 * * * ")
    assert weekly.startswith("0 18 * * 0 ")
    assert pulse.endswith("# feedwatch") and weekly.endswith("# feedwatch")


def test_labels_renamed_and_legacy_constants():
    assert schedule.LABEL_PULSE == "com.feedwatch.pulse"
    assert schedule.CRON_MARK == "# feedwatch"
    assert schedule.LEGACY_CRON_MARK == "# instawatch"


def test_cron_remove_filters_both_marks():
    existing = ["0 9 * * * old pulse # instawatch",
                "0 9 * * * new pulse # feedwatch",
                "0 8 * * * something else"]
    kept = schedule.filter_cron(existing)
    assert kept == ["0 8 * * * something else"]
