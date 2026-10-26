import json

import pytest
import requests

import common
import fetch
import report


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError('secret URL', response=self)


def config(accounts=None):
    return dict(common.DEFAULTS, instagram={'source': 'graph', 'accounts': accounts or ['acc']})


ENV = {'IG_ACCESS_TOKEN': 'synthetic-secret', 'IG_BUSINESS_ID': '1', 'APIFY_TOKEN': 'synthetic-secret'}


@pytest.mark.parametrize('code', [429, 500])
def test_1_network_error_never_persists_secret(monkeypatch, con, code):
    def fail(*args, **kwargs):
        raise requests.HTTPError('https://api/?token=synthetic-secret', response=Response({}, code))
    monkeypatch.setattr(requests, 'post', fail)
    cfg = config()
    cfg['instagram']['source'] = 'apify'
    _, errors = fetch.run_fetch(3, cfg=cfg, env=ENV, con=con)
    saved = con.execute('SELECT last_error FROM account_status').fetchone()[0]
    assert 'synthetic-secret' not in saved
    assert str(code) in saved
    assert 'synthetic-secret' not in report.build_weekly(con, cfg)
    assert errors


@pytest.mark.parametrize('failure', [requests.Timeout, requests.ConnectionError])
@pytest.mark.parametrize('failed_index', [0, 1])
def test_3_account_failure_preserves_other_accounts(monkeypatch, con, failure, failed_index):
    calls = []
    def get(*args, **kwargs):
        calls.append(kwargs['params']['fields'])
        if ('bad' in calls[-1]):
            raise failure('synthetic-secret')
        return Response({'business_discovery': {'media': {'data': [{
            'id': 'ok', 'timestamp': '2026-10-24T10:00:00+00:00', 'permalink': 'https://x'}]}}})
    monkeypatch.setattr(requests, 'get', get)
    accounts = ['good', 'bad'] if failed_index else ['bad', 'good']
    records, errors = fetch.run_fetch(3, cfg=config(accounts), env=ENV, con=con)
    assert [r['post_id'] for r in records] == ['ok']
    assert len(common.latest_metrics(con, 'good')) == 1
    assert set(errors) == {('instagram', 'bad')}


def test_3_empty_accounts_and_empty_media(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: Response({}))
    assert fetch.fetch_graph([], 3, '1', 'x') == ([], {})
    assert fetch.fetch_graph(['a'], 3, '1', 'x') == ([], {})


@pytest.mark.parametrize('tg_fails', [False, True])
def test_5_expired_instagram_does_not_block_telegram(monkeypatch, con, tg_fails):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if 'facebook' in url:
            return Response({'error': {'code': 190, 'message': 'synthetic-secret'}})
        if tg_fails:
            raise requests.Timeout('synthetic-secret')
        return Response({'status': 'ok', 'response': {'items': [
            {'id': 1, 'date': 1792800000, 'text': 'hello', 'views': 10}]}})
    monkeypatch.setattr(requests, 'get', get)
    cfg = config()
    cfg['telegram'] = {'source': 'tgstat', 'channels': ['ch']}
    records, errors = fetch.run_fetch(3, cfg=cfg, env=dict(ENV, TGSTAT_TOKEN='synthetic-secret'), con=con)
    assert any('tgstat' in url for url in calls)
    assert ('instagram', 'acc') in errors
    assert 'synthetic-secret' not in str(errors)
    assert len(common.latest_metrics(con, 'ch', platform='telegram')) == (0 if tg_fails else 1)


@pytest.mark.parametrize('kind,url,expected', [('Video', 'https://cdn/v', 'VIDEO'), ('Image', None, 'IMAGE'), ('Sidecar', None, 'CAROUSEL_ALBUM'), (None, None, None)])
def test_6_apify_media_schema(kind, url, expected, con):
    item = {'shortCode': 'a', 'ownerUsername': 'Acc', 'timestamp': '2026-10-24T00:00:00Z', 'type': kind, 'videoUrl': url}
    record = fetch.normalize_apify(item)
    assert record['media_type'] == expected
    assert record['media_url'] == url
    common.save_posts(con, [record])
    row = con.execute('SELECT media_type, media_url FROM posts').fetchone()
    assert tuple(row) == (expected, url)


def cli_files(monkeypatch, tmp_path, cfg):
    cfg_path = tmp_path / 'config.json'
    cfg_path.write_text(json.dumps(cfg))
    env_path = tmp_path / 'env'
    env_path.write_text('\n'.join('{}={}'.format(k, v) for k, v in ENV.items()))
    # Подменяем только чтение конфигурации, окружения и подключение БД.
    monkeypatch.setattr(common, 'load_config', lambda: dict(common.DEFAULTS, **json.loads(cfg_path.read_text())))
    monkeypatch.setattr(common, 'load_env', lambda: dict(line.split('=', 1) for line in env_path.read_text().splitlines()))


def test_12_real_fetch_cli_network_failure(monkeypatch, con, tmp_path, capsys):
    cli_files(monkeypatch, tmp_path, config())
    monkeypatch.setattr(common, 'connect', lambda: con)
    monkeypatch.setattr('sys.argv', ['fetch.py'])
    def fail(*a, **kw):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr(requests, 'get', fail)
    with pytest.raises(SystemExit) as caught:
        fetch.main()
    assert caught.value.code == 1
    assert con.execute('SELECT last_error FROM account_status').fetchone()[0]


@pytest.mark.parametrize('accounts,status', [(['bad'], 1), (['good', 'bad'], 2), (['good'], 0)])
def test_4_report_distinguishes_collection_failure(monkeypatch, con, tmp_path, capsys, accounts, status):
    cli_files(monkeypatch, tmp_path, config(accounts))
    monkeypatch.setattr(common, 'connect', lambda: con)
    monkeypatch.setattr('sys.argv', ['report.py', 'pulse'])
    def get(*a, **kw):
        if 'bad' in kw['params']['fields']:
            raise requests.Timeout('offline')
        return Response({})
    monkeypatch.setattr(requests, 'get', get)
    if status:
        with pytest.raises(SystemExit) as caught:
            report.main()
        assert caught.value.code == status
    else:
        report.main()
    output = capsys.readouterr()
    if status == 1:
        assert 'Тихо' not in output.out
    if status:
        assert 'сбор' in output.err.lower()


@pytest.mark.parametrize('status', [429, 500])
def test_9_safe_get_retries_temporary_http(monkeypatch, status):
    replies = iter([Response({}, status, {'Retry-After': '2'}), Response({})])
    waits = []
    monkeypatch.setattr(requests, 'get', lambda *a, **kw: next(replies))
    monkeypatch.setattr(fetch.time, 'sleep', waits.append)
    assert fetch.fetch_graph(['acc'], 3, '1', 'x') == ([], {})
    assert waits == [2]


@pytest.mark.parametrize('status', [429, 500, 400])
def test_9_http_failure_is_bounded(monkeypatch, status):
    calls = []
    def get(*a, **kw):
        calls.append(1)
        return Response({}, status)
    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(fetch.time, 'sleep', lambda seconds: None)
    records, errors = fetch.fetch_graph(['acc'], 3, '1', 'x')
    assert records == [] and 'acc' in errors
    assert len(calls) == (1 if status == 400 else 3)


def test_9_timeout_then_success(monkeypatch):
    calls = []
    def get(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise requests.Timeout('offline')
        return Response({})
    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(fetch.time, 'sleep', lambda seconds: None)
    assert fetch.fetch_graph(['acc'], 3, '1', 'x') == ([], {})
    assert len(calls) == 2


@pytest.mark.parametrize('message,expected', [(None, None), ('', ''), ('нет данных', 'нет данных'), ('token=synthetic-secret', 'token=[секрет скрыт]'), ('https://host/path?token=other-secret', '[URL скрыт]')])
def test_1_redaction_boundaries(message, expected):
    assert fetch.redact_error(message, ENV) == expected
    assert fetch.redact_error(fetch.redact_error(message, ENV), ENV) == expected


def test_1_tgstat_http_secret_is_removed_before_storage(monkeypatch, con):
    def fail(*a, **kw):
        raise requests.Timeout('https://tgstat/?token=synthetic-secret')
    monkeypatch.setattr(requests, 'get', fail)
    cfg = dict(common.DEFAULTS, telegram={'source': 'tgstat', 'channels': ['ch']})
    _, errors = fetch.run_fetch(3, cfg=cfg, env={'TGSTAT_TOKEN': 'synthetic-secret'}, con=con)
    assert 'synthetic-secret' not in str(errors)
    assert 'synthetic-secret' not in con.execute('SELECT last_error FROM account_status').fetchone()[0]


@pytest.mark.parametrize('header,expected_calls', [('invalid', 3), ('60', 1), ('0', 3)])
def test_9_retry_after_boundaries(monkeypatch, header, expected_calls):
    calls, waits = [], []
    def get(*a, **kw):
        calls.append(1)
        return Response({}, 429, {'Retry-After': header})
    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(fetch.time, 'sleep', waits.append)
    records, errors = fetch.fetch_graph(['a'], 3, '1', 'x')
    assert records == [] and errors
    assert len(calls) == expected_calls


@pytest.mark.parametrize('accounts,errors,status', [(['a'], {}, 0), (['A', 'a'], {('instagram', 'a'): 'error'}, 1), (['a', 'b'], {('instagram', 'a'): 'error'}, 2)])
def test_4_status_uses_accounts_not_record_count(accounts, errors, status):
    assert fetch.collection_status(config(accounts), errors) == status


def test_9_retry_after_http_date(monkeypatch):
    from email.utils import formatdate
    now = fetch.time.time()
    waits = []
    replies = iter([Response({}, 429, {'Retry-After': formatdate(now + 20, usegmt=True)}), Response({})])
    monkeypatch.setattr(requests, 'get', lambda *a, **kw: next(replies))
    monkeypatch.setattr(fetch.time, 'sleep', waits.append)
    fetch.fetch_graph(['acc'], 3, '1', 'x')
    assert 18 <= waits[0] <= 20


def test_4_partial_pulse_ignores_stale_failed_account(monkeypatch, con, tmp_path, capsys):
    from conftest import make_post
    cfg = dict(config(['good', 'bad']), median_min_posts=3, pulse_multiplier=2)
    cli_files(monkeypatch, tmp_path, cfg)
    monkeypatch.setattr(common, 'connect', lambda: con)
    for account in ['good', 'bad']:
        for i in range(3):
            make_post(con, account + str(i), account, 5 + i, 10, 1)
        make_post(con, account + 'hit', account, 1, 50, 1)
    def get(*a, **kw):
        if 'bad' in kw['params']['fields']:
            raise requests.Timeout('offline')
        return Response({})
    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(fetch.time, 'sleep', lambda seconds: None)
    target = tmp_path / 'pulse.txt'
    monkeypatch.setattr('sys.argv', ['report.py', 'pulse', '--out', str(target)])
    with pytest.raises(SystemExit) as caught:
        report.main()
    assert caught.value.code == 2
    text = target.read_text()
    assert '@good' in text and '@bad' not in text
    assert 'Частичный' in text
