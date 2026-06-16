import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()
from django.contrib.auth.models import User
from apps.clinic.models import Patient

# Create a test patient if not exists
user, created = User.objects.get_or_create(username='testpatient')
if created:
    user.set_password('testpass')
    user.save()
    
patient, p_created = Patient.objects.get_or_create(
    user=user, 
    defaults={'full_name': 'Test Patient', 'phone': '0123456789'}
)

print("Hasattr patient_profile:", hasattr(user, 'patient_profile'))
print("Patient full name:", user.patient_profile.full_name)
