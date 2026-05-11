import json, urllib.request
h = json.load(urllib.request.urlopen('http://127.0.0.1:5001/api/hierarchy'))
def show(n, d=0):
    wc = n.get('ward_count', 0)
    vc = n.get('voter_count', 0)
    print('  ' * d + n['level'] + ': ' + n['name'] + ' (' + str(wc) + 'w ' + str(vc) + 'v)')
    for c in n.get('children', []):
        show(c, d + 1)
show(h)
