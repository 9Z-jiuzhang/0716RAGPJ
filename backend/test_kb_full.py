import requests

r = requests.post('http://localhost:8000/api/v1/auth/login', json={'username': 'admin', 'password': 'Admin123!'})
token = r.json()['data']['access_token']
headers = {'Authorization': f'Bearer {token}'}

print('=== 测试1: 获取知识库列表 ===')
r = requests.get('http://localhost:8000/api/v1/knowledge-bases/', headers=headers)
print('Status:', r.status_code)
data = r.json()
items = data['data']['items']
total = data['data']['total']
print('Total:', total)
for i, item in enumerate(items[:3]):
    print(i+1, '.', item['name'], '(ID:', item['id'][:8], '...)')

kb_id = items[0]['id']
print('\n测试目标知识库ID:', kb_id)

print('\n=== 测试2: 获取知识库详情 ===')
r = requests.get('http://localhost:8000/api/v1/knowledge-bases/' + kb_id, headers=headers)
print('Status:', r.status_code)
if r.status_code == 200:
    d = r.json()['data']
    print('名称:', d['name'])
    print('类型:', d['type'])
    print('可见性:', d['visibility'])
    print('描述:', d['description'])
    print('状态:', d['status'])
else:
    print('错误:', r.text)

print('\n=== 测试3: 更新知识库 ===')
update_data = {
    'name': '测试更新名称',
    'description': '测试更新描述',
}
r = requests.put('http://localhost:8000/api/v1/knowledge-bases/' + kb_id, headers=headers, json=update_data)
print('Status:', r.status_code)
if r.status_code == 200:
    print('更新成功')
else:
    print('错误:', r.text)

print('\n=== 测试4: 验证更新结果 ===')
r = requests.get('http://localhost:8000/api/v1/knowledge-bases/' + kb_id, headers=headers)
print('Status:', r.status_code)
if r.status_code == 200:
    d = r.json()['data']
    print('名称:', d['name'])
    print('描述:', d['description'])
else:
    print('错误:', r.text)

print('\n=== 测试5: 创建新知识库 ===')
new_kb = {
    'name': '测试CRUD知识库',
    'type': 'general',
    'tags': ['test'],
    'description': '用于CRUD测试',
    'visibility': 'public',
    'embedding_model': 'text-embedding-v3',
    'chunk_size': 500,
    'chunk_overlap': 50,
}
r = requests.post('http://localhost:8000/api/v1/knowledge-bases/', headers=headers, json=new_kb)
print('Status:', r.status_code)
if r.status_code == 200:
    new_id = r.json()['data']['id']
    print('创建成功，ID:', new_id)
    
    print('\n=== 测试6: 删除知识库 ===')
    r = requests.delete('http://localhost:8000/api/v1/knowledge-bases/' + new_id, headers=headers)
    print('Status:', r.status_code)
    if r.status_code == 200:
        print('删除成功')
    else:
        print('错误:', r.text)

print('\n=== 所有测试完成 ===')