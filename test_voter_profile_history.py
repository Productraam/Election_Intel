"""End-to-end test for voter profile + ward history feature.

Uploads PDF (v1) -> saves ward -> edits a voter -> re-uploads PDF (v2) ->
verifies stable NQT, voter history, and ward upload history.
"""
import requests
import json
import sys

BASE = 'http://127.0.0.1:5001'
PDF = r'C:\Users\Dhuttarge\Downloads\2024-FC-EROLLGEN-S10-46-FinalRoll-Revision2-ENG-12-WI.pdf'
WARD_NAME = '__test_history_ward__'

# Login as admin so audit/role checks work
print('1. Login as admin...')
r = requests.post(f'{BASE}/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
token = r.json().get('token')
assert token, f'Login failed: {r.text}'
H = {'Authorization': f'Bearer {token}'}

# Cleanup any prior test ward
print('2. Cleanup any prior test ward...')
requests.delete(f'{BASE}/api/wards/{WARD_NAME}', headers=H)

# Upload PDF v1
print('3. Upload PDF (v1)...')
with open(PDF, 'rb') as f:
    r = requests.post(f'{BASE}/api/upload', files={'file': f}, data={'max_pages': '3'}, headers=H)
v1 = r.json()
print(f'   parsed {v1.get("total_voters")} voters')
assert v1.get('total_voters', 0) > 0, f'Upload failed: {r.text}'

# Save as ward (initial)
print('4. Save as ward (initial)...')
r = requests.post(f'{BASE}/api/wards', json={'name': WARD_NAME, 'state': 'Karnataka'}, headers=H)
save1 = r.json()
print(f'   saved: {save1}')
assert save1.get('success'), f'Save failed: {r.text}'
assert save1.get('is_reupload') is False, 'First save should not be a re-upload'

# Pick a voter and capture its NQT
voters = requests.get(f'{BASE}/api/voters?per_page=5', headers=H).json().get('voters', [])
assert voters, 'No voters returned'
target = voters[0]
nqt = target['nqt_id']
print(f'5. Target voter NQT={nqt}, name={target["name"]}')

# GET full profile
print('6. GET voter profile...')
prof = requests.get(f'{BASE}/api/voter/{nqt}', headers=H).json()
assert prof.get('voter'), f'Profile fetch failed: {prof}'
print(f'   profile loaded, history entries: {len(prof.get("history", []))}')

# Edit the voter
print('7. Edit voter (set classification=Pakka, notes="test note")...')
r = requests.put(f'{BASE}/api/voter/{nqt}', json={'classification': 'Pakka', 'notes': 'test note'}, headers=H)
edit_res = r.json()
print(f'   edit result: {edit_res.get("success")}, rejected={edit_res.get("rejected_fields")}')

# Persist edit by saving ward (real-world flow: user clicks Save Ward after editing)
print('7b. Save ward to persist edit...')
requests.post(f'{BASE}/api/wards', json={'name': WARD_NAME, 'state': 'Karnataka'}, headers=H)

# Re-upload SAME PDF (simulates v2)
print('8. Re-upload PDF (v2)...')
with open(PDF, 'rb') as f:
    r = requests.post(f'{BASE}/api/upload', files={'file': f}, data={'max_pages': '3'}, headers=H)
v2 = r.json()
print(f'   parsed {v2.get("total_voters")} voters')

# Save again (re-upload)
print('9. Save ward again (re-upload)...')
r = requests.post(f'{BASE}/api/wards', json={'name': WARD_NAME, 'state': 'Karnataka'}, headers=H)
save2 = r.json()
print(f'   re-save: is_reupload={save2.get("is_reupload")}, diff={save2.get("diff")}')
assert save2.get('is_reupload') is True, 'Second save MUST be a re-upload'

# Reload ward to memory and verify curated fields preserved
print('10. Load ward & verify curated fields preserved...')
requests.get(f'{BASE}/api/wards/{WARD_NAME}', headers=H)
prof2 = requests.get(f'{BASE}/api/voter/{nqt}', headers=H).json()
v_after = prof2.get('voter', {})
print(f'    classification after re-upload: {v_after.get("classification")} (expected Pakka)')
print(f'    notes after re-upload: {v_after.get("notes")!r} (expected "test note")')
assert v_after.get('classification') == 'Pakka', 'Curated classification was overwritten by re-upload!'
assert v_after.get('notes') == 'test note', 'Curated notes were overwritten by re-upload!'

# Verify ward upload history
print('11. GET ward upload history...')
hist = requests.get(f'{BASE}/api/wards/{WARD_NAME}/history', headers=H).json()
print(f'    history entries: {len(hist.get("history", []))}')
for h in hist.get('history', []):
    print(f'    - {h["uploaded_at"]} by {h["uploaded_by"]}: '
          f'+{h["voters_added"]} ~{h["voters_updated"]} -{h["voters_removed"]} ={h["voters_unchanged"]}')
assert len(hist.get('history', [])) >= 2, 'Should have at least 2 history rows'

# Verify voter history shows the edit
print('12. Verify voter history shows manual edit...')
v_hist = prof2.get('history', [])
edit_rows = [h for h in v_hist if h['field'] == 'classification' and h['action'] == 'update_voter']
print(f'    classification edits in history: {len(edit_rows)}')
assert any(h['new_value'] == 'Pakka' for h in edit_rows), 'Edit not in history'

# Cleanup
print('13. Cleanup...')
requests.delete(f'{BASE}/api/wards/{WARD_NAME}', headers=H)

print('\n✅ ALL CHECKS PASSED')
