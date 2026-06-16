import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()
from django.test import Client

client = Client(HTTP_HOST='127.0.0.1:8000')
# test login with next parameter
response = client.post('/system/users/login/?next=/system/patients/', {
    'username': 'testpatient',
    'password': 'testpass'
})
print("Login status:", response.status_code)
print("Redirect URL:", response.url if hasattr(response, 'url') else 'No redirect')
