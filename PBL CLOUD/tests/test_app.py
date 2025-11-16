import os
import json
import sys
import importlib
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    # isolate data files per-test by pointing the app to a temp data dir
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))
    # ensure a fresh import of the app module so it picks up APP_DATA_DIR
    if 'app' in sys.modules:
        del sys.modules['app']
    app_mod = importlib.import_module('app')
    # initialize required sample files inside the temporary data dir
    users_file = app_mod.USERS_FILE
    votes_file = app_mod.VOTES_FILE
    from werkzeug.security import generate_password_hash
    users_data = {"voters": [{"id": "voter1", "name": "Test Voter", "password_hash": generate_password_hash("password1")} ]}
    with open(users_file, 'w', encoding='utf-8') as uf:
        json.dump(users_data, uf)
    with open(votes_file, 'w', encoding='utf-8') as vf:
        json.dump({"options": {"optionA": 0, "optionB": 0, "optionC": 0}, "records": []}, vf)

    app = app_mod.app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_login_and_vote(client):
    # use sample credentials created at runtime in app if needed
    resp = client.post('/api/login', json={"id": "voter1", "password": "password1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['id'] == 'voter1'

    vote_resp = client.post('/api/vote', json={"id": "voter1", "option": "optionA"})
    assert vote_resp.status_code == 200
    vote_data = vote_resp.get_json()
    assert vote_data['success'] is True
    assert vote_data['option_counts']['optionA'] == 1


# (client fixture provided above)
