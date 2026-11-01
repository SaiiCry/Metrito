"""
Generador de sitio estático empaquetado para GitHub Pages (SIMMA / Metrito).
Exporta el HTML compilado, los datos de red JSON serializados (/api/network/) y todos los activos estáticos a docs/
para que la página funcione 100% de forma autónoma alojada en GitHub Pages.
"""

import os
import sys
import shutil
import json
from pathlib import Path

# Configurar Django para reutilizar las vistas y serializadores del sistema
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["DJANGO_SETTINGS_MODULE"] = "metrito_config.settings"

import django
django.setup()

from django.test import RequestFactory
from network.views import api_network_data

BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs"

def build_github_pages_bundle():
    print("Iniciando empaquetado para GitHub Pages...")
    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Exportar datos de red (/api/network/) en formato estático data/network.json
    data_dir = DOCS_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    rf = RequestFactory()
    req = rf.get("/api/network/")
    resp = api_network_data(req)
    network_data_json = resp.content.decode("utf-8")
    (data_dir / "network.json").write_text(network_data_json, encoding="utf-8")
    print(f" -> data/network.json exportado ({len(network_data_json) // 1024} KB)")

    # 2. Copiar archivos cartográficos (logo, red_metro.svg, json)
    cartografia_dest = DOCS_DIR / "cartografia"
    cartografia_dest.mkdir(parents=True, exist_ok=True)
    src_cartografia = BASE_DIR / "cartografia"
    for filename in ["logo_metro.svg", "red_metro.svg", "red_metro.json"]:
        src_file = src_cartografia / filename
        if src_file.exists():
            shutil.copy2(src_file, cartografia_dest / filename)
    print(" -> cartografia/ copiada a docs/")

    # 3. Copiar recursos estáticos (CSS, JS)
    static_dest = DOCS_DIR / "static" / "network"
    static_dest.mkdir(parents=True, exist_ok=True)
    src_static = BASE_DIR / "network" / "static" / "network"
    if src_static.exists():
        shutil.copytree(src_static / "css", static_dest / "css", dirs_exist_ok=True)
        shutil.copytree(src_static / "js", static_dest / "js", dirs_exist_ok=True)
    print(" -> static/ copiado a docs/")

    # 4. Compilar index.html reemplazando tags de Django ({% static %}, endpoints dinámicos) por rutas relativas
    src_template = BASE_DIR / "network" / "templates" / "network" / "index.html"
    raw_html = src_template.read_text(encoding="utf-8")

    # Limpiar template tags de Django
    clean_html = raw_html.replace("{% load static %}", "")
    clean_html = clean_html.replace("{% static 'network/css/styles.css' %}", "static/network/css/styles.css")
    clean_html = clean_html.replace("{% static 'network/js/app.js' %}", "static/network/js/app.js")
    clean_html = clean_html.replace('src="/api/cartografia/logo/"', 'src="cartografia/logo_metro.svg"')

    (DOCS_DIR / "index.html").write_text(clean_html, encoding="utf-8")
    print(" -> docs/index.html generado exitosamente")

    # 5. Crear archivo .nojekyll para evitar que GitHub Pages ignore carpetas estáticas
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    print("¡Empaquetado completado! El directorio docs/ está listo para desplegar en GitHub Pages.")

if __name__ == "__main__":
    build_github_pages_bundle()
