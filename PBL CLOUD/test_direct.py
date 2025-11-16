#!/usr/bin/env python
import sys
sys.path.insert(0, '.')
from app import app

# Create test client
client = app.test_client()

# Test home page
resp = client.get('/')
print(f"GET / : {resp.status_code}")
print(f"Response length: {len(resp.data)}")

# Test chat endpoint
resp = client.post('/api/chat', json={'message': 'hello'})
print(f"POST /api/chat : {resp.status_code}")
print(f"Response: {resp.get_json()}")
