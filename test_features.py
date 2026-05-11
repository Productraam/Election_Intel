"""Test tags, history, and report generation."""
import json
import time

# Load real ward data
with open('saved_wards/Khajuri.json', 'r', encoding='utf-8') as f:
    ward = json.load(f)

voters = ward['voters']
meta = ward.get('metadata', {})
print(f'Loaded {len(voters)} voters')

# Ensure backward compat — voters without new fields should work
v = voters[0]
print(f'Voter fields: tags={v.get("tags")}, caste={v.get("caste")}, party_lean={v.get("party_lean")}')

# Test analytics
from analytics import ElectionAnalytics
ea = ElectionAnalytics(voters, meta)

# Tag analysis (no tags yet)
tags = ea.get_tag_analysis()
print(f'\nTag analysis: tagged={tags["tagged_voters"]}, tags={len(tags["tags"])}')

# Scheme coverage (no tags yet)
scheme = ea.get_scheme_coverage()
print(f'Scheme coverage: beneficiaries={scheme["total_beneficiaries"]}')

# Party lean
party = ea.get_party_lean_analysis()
print(f'Party lean: {len(party["parties"])} parties')

# Add some tags to a few voters
for i, v in enumerate(voters[:50]):
    v['tags'] = ['PM-KISAN']
    v['caste'] = 'Lingayat'
for i, v in enumerate(voters[50:80]):
    v['tags'] = ['Ration Card (BPL)']
    v['caste'] = 'SC'
for i, v in enumerate(voters[80:100]):
    v['tags'] = ['PM-KISAN', 'MNREGA']
    v['party_lean'] = 'BJP'

# Re-run analytics
ea2 = ElectionAnalytics(voters, meta)
tags2 = ea2.get_tag_analysis()
print(f'\nAfter tagging: tagged={tags2["tagged_voters"]}, tags={len(tags2["tags"])}')
for t in tags2['tags']:
    print(f'  {t["tag"]}: {t["count"]} ({t["percent"]}%)')

scheme2 = ea2.get_scheme_coverage()
print(f'Scheme beneficiaries: {scheme2["total_beneficiaries"]}')
print(f'Scheme types: {scheme2["scheme_types"]}')

# Test historical analysis
history = [
    {'year': 2023, 'election_type': 'Assembly', 'parties': [
        {'name': 'BJP', 'votes': 45000, 'candidate': 'A'},
        {'name': 'INC', 'votes': 42000, 'candidate': 'B'},
        {'name': 'JDS', 'votes': 8000, 'candidate': 'C'},
    ], 'total_votes': 95000, 'turnout_pct': 72, 'winner': 'BJP'},
    {'year': 2018, 'election_type': 'Assembly', 'parties': [
        {'name': 'BJP', 'votes': 40000, 'candidate': 'A'},
        {'name': 'INC', 'votes': 43000, 'candidate': 'B'},
    ], 'total_votes': 83000, 'turnout_pct': 68, 'winner': 'INC'},
]
ha = ElectionAnalytics.get_historical_analysis(history)
print(f'\nHistory: {ha["total_elections"]} elections, avg_turnout={ha["avg_turnout"]}%')
for p in ha['party_summary']:
    print(f'  {p["party"]}: {p["total_votes"]} total, {p["wins"]} wins')

# Test winning formula with history
wf = ea2.get_winning_formula(history)
for booth, f in wf.items():
    print(f'\nBooth {booth}: turnout={f["turnout_rate_used"]}% ({f["turnout_source"]}), '
          f'target={f["winning_target"]}, pakka={f["confirmed_pakka"]}, status={f["status"]}')

# Test report generation
print('\nGenerating PDF report...')
meta['_election_history'] = history
from report_generator import generate_report
start = time.time()
buf = generate_report(voters, meta)
elapsed = time.time() - start
pdf_bytes = buf.getvalue()
print(f'PDF generated in {elapsed:.1f}s ({len(pdf_bytes)} bytes)')

with open('test_full_report.pdf', 'wb') as f:
    f.write(pdf_bytes)
print('Saved: test_full_report.pdf')
print('\nSUCCESS')
