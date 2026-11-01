"""
WSGI config for metrito_config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'metrito_config.settings')

# Auto-migrar y sembrar automáticamente cuando se conecta una base de datos en la nube (Neon Postgres / Vercel)
if os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL"):
    try:
        import django
        django.setup()
        from django.core.management import call_command
        call_command('migrate', interactive=False)
        from network.seed import seed_database
        seed_database(force_reset=False)
    except Exception as e:
        print("[Auto-migrate notice]:", e)

application = get_wsgi_application()
app = application
