import requests
import re

s = requests.Session()
lp = s.get('http://127.0.0.1:5000/auth/school-login')
m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', lp.text)
r = s.post('http://127.0.0.1:5000/auth/school-login',
           data={'csrf_token': m.group(1), 'admin_name': 'hubertadmin', 'password': 'test123'},
           allow_redirects=True)
h = r.text
print('status', r.status_code)
print('chart filter present:', 'id="sdChartClassFilter"' in h)
print('has All Classes default:', 'sdChartClassFilter" class="sd-student-class-select" aria-label="Filter students by class">\n                <option value="">All Classes</option>' in h)
