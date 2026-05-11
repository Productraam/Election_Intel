"""Test the report API endpoint."""
import requests

# Load ward
res = requests.get('http://127.0.0.1:5001/api/wards/Khajuri')
print(f'Load ward: {res.status_code}')
d = res.json()
total = d.get('total_voters', 0)
print(f'Loaded: {total} voters')

# Download report
res2 = requests.get('http://127.0.0.1:5001/api/report/pdf')
ctype = res2.headers.get('content-type', '')
print(f'Report: {res2.status_code}, size={len(res2.content)} bytes, type={ctype}')
if res2.status_code == 200:
    with open('test_api_report.pdf', 'wb') as f:
        f.write(res2.content)
    print('Saved test_api_report.pdf - SUCCESS')
else:
    print(res2.text[:500])
