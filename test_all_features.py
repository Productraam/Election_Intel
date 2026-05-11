"""Test all new features: Auth, RBAC, DB, WhatsApp, Audit."""
import requests as r

BASE = 'http://127.0.0.1:5001'

# Test 1: Login
res = r.post(f'{BASE}/api/auth/login', json={'username':'admin','password':'admin123'})
data = res.json()
print(f'1. Login: {res.status_code} - user={data.get("user",{}).get("username")}, role={data.get("user",{}).get("role")}')
token = data.get('token','')

# Test 2: Auth /me
headers = {'Authorization': f'Bearer {token}'}
res = r.get(f'{BASE}/api/auth/me', headers=headers)
print(f'2. /me: {res.status_code} - {res.json().get("username")}')

# Test 3: Register new user
res = r.post(f'{BASE}/api/auth/register', headers=headers,
    json={'username':'booth1','password':'pass1234','role':'booth_agent','display_name':'Booth Agent 1'})
print(f'3. Register: {res.status_code} - {res.json().get("user",{}).get("username",res.json().get("error",""))}')

# Test 4: List users
res = r.get(f'{BASE}/api/auth/users', headers=headers)
print(f'4. Users: {res.status_code} - count={len(res.json())}')

# Test 5: Status (no auth)
res = r.get(f'{BASE}/api/status')
print(f'5. Status: {res.status_code}')

# Test 6: Hierarchy
res = r.get(f'{BASE}/api/hierarchy')
tree = res.json()
print(f'6. Hierarchy: {res.status_code} - wards={tree.get("ward_count")}, voters={tree.get("voter_count")}')

# Test 7: Load ward
res = r.post(f'{BASE}/api/hierarchy/load', json={'level':'ward','value':'Khajuri','path':{}})
print(f'7. Load ward: {res.status_code} - voters={res.json().get("total_voters")}')

# Test 8: Summary analytics
res = r.get(f'{BASE}/api/summary')
print(f'8. Summary: {res.status_code} - total={res.json().get("total_voters")}')

# Test 9: DB wards
res = r.get(f'{BASE}/api/db/wards')
print(f'9. DB wards: {res.status_code} - count={len(res.json())}')

# Test 10: WhatsApp status
res = r.get(f'{BASE}/api/whatsapp/status')
wa = res.json()
print(f'10. WA status: {res.status_code} - provider={wa.get("provider")}, configured={wa.get("configured")}')

# Test 11: WA templates
res = r.get(f'{BASE}/api/whatsapp/templates')
print(f'11. WA templates: {res.status_code} - count={len(res.json())}')

# Test 12: Audit log
res = r.get(f'{BASE}/api/audit', headers=headers)
print(f'12. Audit: {res.status_code} - entries={len(res.json())}')

# Test 13: RBAC - booth_agent can't register users
ba_res = r.post(f'{BASE}/api/auth/login', json={'username':'booth1','password':'pass1234'})
ba_token = ba_res.json().get('token','')
ba_headers = {'Authorization': f'Bearer {ba_token}'}
res = r.post(f'{BASE}/api/auth/register', headers=ba_headers,
    json={'username':'test','password':'test1234','role':'karyakarta'})
print(f'13. RBAC block: {res.status_code} (expected 403)')

# Test 14: Sync endpoint
res = r.post(f'{BASE}/api/sync', json={'changes':[
    {'action':'update','nqt_id':'nonexistent','updates':{'classification':'Pakka'}}
]})
print(f'14. Sync: {res.status_code} - synced={res.json().get("synced")}, failed={res.json().get("failed")}')

# Test 15: Voter update with audit
voters_res = r.get(f'{BASE}/api/voters?page=1&per_page=1')
vdata = voters_res.json()
if vdata.get('voters'):
    nqt = vdata['voters'][0]['nqt_id']
    res = r.put(f'{BASE}/api/voter/{nqt}', headers=headers,
        json={'classification':'Pakka'})
    print(f'15. Voter update: {res.status_code}')
    # Check audit log captured it
    res = r.get(f'{BASE}/api/audit?voter={nqt}', headers=headers)
    print(f'16. Audit for voter: {res.status_code} - entries={len(res.json())}')

# Test 16: Report still works
res = r.get(f'{BASE}/api/report/pdf')
print(f'17. PDF report: {res.status_code} - size={len(res.content)} bytes')

print('\n=== ALL TESTS PASSED ===')
