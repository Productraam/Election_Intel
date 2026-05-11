"""Test hierarchy API endpoints."""
import requests
import json

BASE = 'http://127.0.0.1:5001'

# Test hierarchy tree
print('=== GET /api/hierarchy ===')
res = requests.get(BASE + '/api/hierarchy')
tree = res.json()
print('Status:', res.status_code)
print('Root:', tree['name'], '|', tree['ward_count'], 'wards |', tree['voter_count'], 'voters')
for c in tree['children']:
    print(' ', c['name'], '[' + c['level_label'] + ']', c['ward_count'], 'wards', c['voter_count'], 'voters')
    for c2 in c.get('children', []):
        print('   ', c2['name'], '[' + c2['level_label'] + ']')

# Test loading aggregated data at district level
print('\n=== POST /api/hierarchy/load (state=Karnataka) ===')
res = requests.post(BASE + '/api/hierarchy/load', json={
    'level': 'state', 'value': 'Karnataka', 'path': {}
})
data = res.json()
print('Status:', res.status_code)
print('Total voters:', data.get('total_voters'))
print('Ward count:', data.get('ward_count'))
print('Wards:', data.get('wards'))

# Test report on aggregated data
print('\n=== GET /api/report/pdf ===')
res = requests.get(BASE + '/api/report/pdf')
print('Status:', res.status_code)
print('PDF size:', len(res.content), 'bytes')

# Test loading all data
print('\n=== POST /api/hierarchy/load (root) ===')
res = requests.post(BASE + '/api/hierarchy/load', json={
    'level': 'root', 'value': 'All Data', 'path': {}
})
data = res.json()
print('Status:', res.status_code)
print('Total voters:', data.get('total_voters'))
print('Ward count:', data.get('ward_count'))

print('\nSUCCESS')
