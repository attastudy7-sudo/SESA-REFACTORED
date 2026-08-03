import requests
import re

s = requests.Session()
lp = s.get('http://127.0.0.1:5000/auth/school-login')
print('login page status:', lp.status_code, 'len:', len(lp.text))
print('has form:', '<form' in lp.text)
toks = re.findall(r'name="csrf_token"[^>]*value="([^"]+)"', lp.text)
print('csrf tokens found:', len(toks), toks[:1])
r = s.post('http://127.0.0.1:5000/auth/school-login',
           data={'csrf_token': toks[0] if toks else '', 'admin_name': 'hubertadmin', 'password': 'test123'},
           allow_redirects=False)
print('post status:', r.status_code, 'loc:', r.headers.get('Location'))
body = r.text[:800]
print('body snippet:', body.replace('\n', ' ')[:700])
