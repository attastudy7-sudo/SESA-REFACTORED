import requests
import re

s = requests.Session()
lp = s.get('http://127.0.0.1:5000/auth/school-login')
m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', lp.text)
r = s.post('http://127.0.0.1:5000/auth/school-login',
           data={'csrf_token': m.group(1), 'admin_name': 'hubertadmin', 'password': 'test123'},
           allow_redirects=True)
h = r.text
print('status', r.status_code, 'url', r.url)
for token in ['sdChartClassFilter', 'sd-card__filters', 'sdMainContent', 'sdChartTitle', 'sdClassFilter', 'sd-student-list']:
    print(token, '->', token in h)
i = h.find('sdMainContent')
if i != -1:
    print('mainContent snippet:', h[i-40:i+400].replace('\n', '\\n')[:440])
