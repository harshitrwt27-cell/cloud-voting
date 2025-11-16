import os
from unittest.mock import patch
import pytest
import importlib
import sys


@pytest.fixture
def client(tmp_path, monkeypatch):
    # isolate app data and provide a realistic test OPENAI key (long enough to pass demo check)
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-proj-real-test-key-1234567890abcdefgh')
    if 'app' in sys.modules:
        del sys.modules['app']
    app_mod = importlib.import_module('app')
    app = app_mod.app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_chat_success(client):
    # Mock the new OpenAI client
    mock_response = type('Response', (), {
        'choices': [type('Choice', (), {
            'message': type('Message', (), {'content': 'This is a test reply'})()
        })()]
    })()
    with patch('app.OpenAI') as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.chat.completions.create.return_value = mock_response
        rv = client.post('/api/chat', json={'message': 'hello'})
        assert rv.status_code == 200
        j = rv.get_json()
        assert 'reply' in j
        assert j['reply'] == 'This is a test reply'


def test_chat_demo_mode(monkeypatch):
    # Test demo mode with short/invalid key
    monkeypatch.setenv('APP_DATA_DIR', '/tmp/test')
    monkeypatch.setenv('OPENAI_API_KEY', 'testkey')
    if 'app' in sys.modules:
        del sys.modules['app']
    app_mod = importlib.import_module('app')
    app = app_mod.app
    app.config['TESTING'] = True
    with app.test_client() as c:
        rv = c.post('/api/chat', json={'message': 'hello'})
        assert rv.status_code == 200
        j = rv.get_json()
        assert 'reply' in j
        assert '[DEMO MODE]' in j['reply']


def test_chat_missing_message(client):
    rv = client.post('/api/chat', json={})
    assert rv.status_code == 400


def test_chat_no_api_key(monkeypatch):
    # Test demo mode when OPENAI_API_KEY is not set
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    # import a fresh app so it picks up current env
    if 'app' in sys.modules:
        del sys.modules['app']
    app_mod = importlib.import_module('app')
    app = app_mod.app
    app.config['TESTING'] = True
    with app.test_client() as c:
        rv = c.post('/api/chat', json={'message': 'hi'})
        assert rv.status_code == 200
        j = rv.get_json()
        assert 'reply' in j
        assert '[DEMO MODE]' in j['reply']
