import requests
import json

token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJlOTdlMTBjNC02MjRhLTQ2OGQtYjkzNi1hNWE2YzYzYTAwMGMiLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzg0MjU4OTAzfQ.33my4NH1mqm9K6UgZs5tIGT2EezJy-twO1tI4XAsAPU'
headers = {'Authorization': f'Bearer {token}'}

print('=== 测试知识库列表 ===')
r = requests.get('http://localhost:8000/api/v1/knowledge-bases/', headers=headers)
print(f'Status: {r.status_code}')
data = r.json()
print(f"总数: {data.get('data', {}).get('total', 0)}")
for kb in data.get('data', {}).get('items', []):
    print(f"  - {kb['name']} (类型: {kb['type']}, 可见性: {kb['visibility']}, 文档数: {kb['document_count']}, 分段数: {kb['chunk_count']})")

print()
print('=== 测试知识库详情 ===')
kb_id = data.get('data', {}).get('items', [{}])[0].get('id')
if kb_id:
    r = requests.get(f'http://localhost:8000/api/v1/knowledge-bases/{kb_id}', headers=headers)
    print(f'Status: {r.status_code}')
    detail = r.json()
    d = detail.get('data', {})
    print(f"名称: {d.get('name')}")
    print(f"描述: {d.get('description')}")
    print(f"状态: {d.get('status')}")
    print(f"当前索引版本: {d.get('current_index_version')}")

print()
print('=== 测试按名称筛选 ===')
r = requests.get('http://localhost:8000/api/v1/knowledge-bases/?name=技术', headers=headers)
print(f'Status: {r.status_code}')
data = r.json()
print(f"匹配数量: {data.get('data', {}).get('total', 0)}")

print()
print('=== 测试按类型筛选 ===')
r = requests.get('http://localhost:8000/api/v1/knowledge-bases/?type=technical_doc', headers=headers)
print(f'Status: {r.status_code}')
data = r.json()
print(f"匹配数量: {data.get('data', {}).get('total', 0)}")

print()
print('=== 测试创建知识库 ===')
new_kb = {
    'name': '测试新建知识库',
    'type': 'general',
    'tags': ['测试', '新建'],
    'description': '通过API创建的测试知识库',
    'visibility': 'restricted',
    'embedding_model': 'text-embedding-v3',
    'chunk_size': 500,
    'chunk_overlap': 50,
}
r = requests.post('http://localhost:8000/api/v1/knowledge-bases/', headers=headers, json=new_kb)
print(f'Status: {r.status_code}')
result = r.json()
if r.status_code == 200:
    print(f"创建成功: {result.get('data', {}).get('name')}")
else:
    print(f"错误: {result}")

print()
print('=== 测试更新知识库 ===')
kb_id = result.get('data', {}).get('id') if r.status_code == 200 else None
if kb_id:
    update_data = {
        'name': '测试新建知识库(已修改)',
        'description': '通过API更新后的描述',
    }
    r = requests.put(f'http://localhost:8000/api/v1/knowledge-bases/{kb_id}', headers=headers, json=update_data)
    print(f'Status: {r.status_code}')
    if r.status_code == 200:
        print('更新成功')

print()
print('测试完成!')