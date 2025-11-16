import pytest
import importlib
import sys


@pytest.fixture
def client(tmp_path, monkeypatch):
    # isolate the app data per-test
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))
    if 'app' in sys.modules:
        del sys.modules['app']
    app_mod = importlib.import_module('app')
    app = app_mod.app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_verify_match_any(client, monkeypatch):
    faces = {'voter1': [0, 0, 0], 'voter2': [1, 1, 1]}
    monkeypatch.setattr('app.load_faces', lambda: faces)
    rv = client.post('/api/face/verify', json={'descriptor': [0, 0, 0]})
    assert rv.status_code == 200
    j = rv.get_json()
    assert j.get('match') is True
    assert j.get('id') == 'voter1'


def test_verify_no_match(client, monkeypatch):
    faces = {'voter1': [1, 1, 1]}
    monkeypatch.setattr('app.load_faces', lambda: faces)
    rv = client.post('/api/face/verify', json={'descriptor': [10, 10, 10]})
    assert rv.status_code == 200
    j = rv.get_json()
    assert j.get('match') is False


def test_verify_by_id_success(client, monkeypatch):
    faces = {'voter1': [0, 0, 0]}
    monkeypatch.setattr('app.load_faces', lambda: faces)
    rv = client.post('/api/face/verify', json={'descriptor': [0, 0, 0], 'id': 'voter1'})
    assert rv.status_code == 200
    j = rv.get_json()
    assert j.get('match') is True


def test_verify_by_id_missing(client, monkeypatch):
    faces = {'voter1': [0, 0, 0]}
    monkeypatch.setattr('app.load_faces', lambda: faces)
    rv = client.post('/api/face/verify', json={'descriptor': [0, 0, 0], 'id': 'nope'})
    assert rv.status_code == 404
