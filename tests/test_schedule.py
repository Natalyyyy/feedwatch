import common
import schedule


def test_parse_time():
    assert schedule.parse_time("18:05") == (18, 5)


def test_plist_weekly_has_weekday():
    xml = schedule.plist_xml("com.instawatch.weekly", "weekly", 18, 0, weekday=0)
    assert "<string>weekly</string>" in xml
    assert "<key>Weekday</key><integer>0</integer>" in xml
    assert "<string>--send</string>" in xml
    assert "report.py" in xml


def test_plist_pulse_no_weekday():
    xml = schedule.plist_xml("com.instawatch.pulse", "pulse", 10, 0)
    assert "Weekday" not in xml


def test_cron_lines():
    cfg = dict(common.DEFAULTS, weekly_day="sun", weekly_time="18:00", pulse_time="10:30")
    pulse, weekly = schedule.cron_lines(cfg)
    assert pulse.startswith("30 10 * * * ")
    assert weekly.startswith("0 18 * * 0 ")
    assert pulse.endswith("# instawatch") and weekly.endswith("# instawatch")
