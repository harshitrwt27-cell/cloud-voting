import requests
import os
import time

# Wait for server to start
time.sleep(2)

os.environ['OPENAI_API_KEY'] = 'sk-test'

try:
    resp = requests.post('http://127.0.0.1:5000/api/chat', json={'message': 'hello'})
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json()}")
except Exception as e:
    print(f"Error: {e}")
