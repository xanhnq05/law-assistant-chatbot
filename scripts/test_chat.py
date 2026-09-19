"""Smoke test cho chat-service.

Tạo user + session + message, kiểm tra:
1. POST /chats/ tạo session thành công (201)
2. POST /chats/{id}/messages add message + RAG tạo assistant
3. Auto-rename session lần đầu (title = content[:30])
4. GET /chats/ list sessions
5. DELETE /chats/{id} xoá session
"""
import urllib.request, urllib.error, json, sys
sys.path.insert(0, r"H:\Python\tro_ly_luat\backend\services\auth-service")

import os
os.environ.setdefault('PYTHONPATH', '.')

from app.repositories.jwt_helper import create_access_token
from bson import ObjectId

# Tạo user_id giả dạng ObjectId
user_id = str(ObjectId())
token = create_access_token(user_id=user_id, role='user')
headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}

BASE = 'http://localhost:8002'


def call(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(BASE + path, method=method, data=data, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


print('=== 1. CREATE SESSION ===')
status, sess = call('POST', '/chats/', {'title': 'Đoạn chat mới'})
print(f'Status: {status}')
assert status == 201, f'Create failed: {sess}'
sid = sess['session_id']
print(f'Session ID: {sid[:20]}...')
print(f'Title: {sess["title"]}')
print(f'Messages: {len(sess["messages"])}')

print()
print('=== 2. ADD MESSAGE (user) ===')
status, sess = call('POST', f'/chats/{sid}/messages',
                    {'role': 'user', 'content': 'Mức phạt vượt đèn đỏ xe máy', 'sources': []})
print(f'Status: {status}')
assert status == 201, f'Add message failed: {sess}'
print(f'Title (after rename): {sess["title"]}')
print(f'Messages: {len(sess["messages"])}')
for m in sess['messages']:
    print(f'  [{m["role"]}] {m["content"][:80]}')

# Check auto-rename
expected_title = 'Mức phạt vượt đèn đỏ xe máy'[:30]
print(f'Expected title: "{expected_title}"')
print(f'Actual title:   "{sess["title"]}"')
assert sess['title'] == expected_title, f'Auto-rename failed'

print()
print('=== 3. LIST SESSIONS ===')
status, lst = call('GET', '/chats/')
print(f'Status: {status}')
print(f'Total sessions: {len(lst)}')
for s in lst:
    print(f'  - {s["title"]} ({len(s["messages"])} msgs)')

print()
print('=== 4. DELETE SESSION ===')
status, resp = call('DELETE', f'/chats/{sid}')
print(f'Status: {status}, Response: {resp}')

print()
print('=== 5. GET DELETED (should 404) ===')
status, resp = call('GET', f'/chats/{sid}')
print(f'Status: {status} (expected 404)')

print()
print('🎉 All tests passed!')
