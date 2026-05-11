"""Test hierarchy module."""
import json

# Add hierarchy info to existing Khajuri ward
with open('saved_wards/Khajuri.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

data['hierarchy'] = {
    'state': 'Karnataka',
    'district': 'Kalaburagi',
    'taluka': 'Aland',
    'hobli': 'Aland',
    'gram_panchayat': 'Khajuri GP',
    'village': 'Khajuri'
}

with open('saved_wards/Khajuri.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('Updated Khajuri with hierarchy info')

# Test build_tree
from hierarchy import build_tree, find_ward_files, load_combined_voters
tree = build_tree()

def show(node, depth=0):
    prefix = '  ' * depth
    if node['level'] == 'ward':
        info = str(node['voter_count']) + ' voters'
    else:
        info = str(node['ward_count']) + ' wards, ' + str(node['voter_count']) + ' voters'
    print(prefix + node['name'] + ' [' + node['level_label'] + '] - ' + info)
    for c in node.get('children', []):
        show(c, depth + 1)

show(tree)

# Test find_ward_files
print('\n--- Find wards in Kalaburagi district ---')
files = find_ward_files('district', 'Kalaburagi')
print('Found:', files)

# Test aggregation
print('\n--- Load combined voters for state=Karnataka ---')
files = find_ward_files('state', 'Karnataka')
voters, meta = load_combined_voters(files)
print('Total voters:', len(voters))
print('Ward names:', meta.get('_ward_names'))
print('Ward count:', meta.get('_ward_count'))

print('\nSUCCESS')
