import os
import glob

directory = r'c:\Users\ANONYMOUS\Desktop\Dev Projects\Python Projects\SESA_refactored\app\templates\auth'
for filepath in glob.glob(os.path.join(directory, '*.html')):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace href="#" for Privacy
    content = content.replace('href="#">Privacy</a>', 'href="{{ url_for(\'main.privacy\') }}">Privacy</a>')
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# Special case for login.html
login_file = os.path.join(directory, 'login.html')
try:
    with open(login_file, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace('Privacy First</span>', '<a href="{{ url_for(\'main.privacy\') }}" class="hover:text-white" style="text-decoration:none; color:inherit;">Privacy First</a></span>')
    with open(login_file, 'w', encoding='utf-8') as f:
        f.write(content)
except Exception as e:
    print(f"Error modifying login.html: {e}")

print("Privacy links updated successfully.")
