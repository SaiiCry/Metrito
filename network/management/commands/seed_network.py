"""
Comando de administración Django para inicializar o restaurar la base de datos
de la red SMyT (python manage.py seed_network [--reset]).
"""

from django.core.management.base import BaseCommand
from network.seed import seed_database


class Command(BaseCommand):
    help = "Inicializa la base de datos con las 34 líneas, 828 estaciones de Metro + 171 de Autobuses Articulados y alertas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Fuerza la recreación completa de los datos originales de metro2.pdf y metro2.png",
        )

    def handle(self, *args, **options):
        result = seed_database(force_reset=options["reset"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Red SMyT lista: {result['lines']} líneas, {result['stations']} nodos únicos, "
                f"{result['line_stations']} paradas en línea (828 Metro + 171 Autobuses Articulados)."
            )
        )
