import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()
from django.test import Client
from django.contrib.auth.models import User

client = Client()
client.login(username='testpatient', password='testpass')
response = client.get('/portal/')
print("Status code:", response.status_code)
if response.status_code != 200:
    print(response.content.decode('utf-8')[:500])
else:
    content = response.content.decode('utf-8')
    print("Content length:", len(content))
    print("Title:", content[content.find('<title>'):content.find('</title>')+8])
    if "Không có lịch hẹn sắp tới hay hóa đơn chưa thanh toán" in content:
        print("Empty state rendered!")
