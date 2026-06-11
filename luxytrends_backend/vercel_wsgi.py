import os
from django.core.wsgi import get_wsgi_application

# Replace 'luxytrends_backend.settings' with your actual settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "luxytrends_backend.settings")

application = get_wsgi_application()