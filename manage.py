# #!/usr/bin/env python
# """Django's command-line utility for administrative tasks."""
# import os
# import sys


# def main():
#     """Run administrative tasks."""
#     os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'duds_catalog.settings')
#     try:
#         from django.core.management import execute_from_command_line
#     except ImportError as exc:
#         raise ImportError(
#             "Couldn't import Django. Are you sure it's installed and "
#             "available on your PYTHONPATH environment variable? Did you "
#             "forget to activate a virtual environment?"
#         ) from exc
#     execute_from_command_line(sys.argv)


# if __name__ == '__main__':
#     main()

#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# --- INICIO DEL PARCHE SEGURO ---
# Esto detecta si estás en Windows ('nt'). Si es así, aplica el truco.
# Si estás en cPanel (Linux), esto se ignora y no afecta nada.
if os.name == 'nt':
    try:
        import pymysql
        # Engañamos a Django diciendo que es la versión correcta
        pymysql.version_info = (2, 2, 1, 'final', 0) 
        # Forzamos la instalación aquí también para asegurar que el parche cargue antes
        pymysql.install_as_MySQLdb()
    except ImportError:
        pass
# --- FIN DEL PARCHE SEGURO ---

def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'duds_catalog.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()