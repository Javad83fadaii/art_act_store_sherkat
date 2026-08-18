import importlib.util

celery_app = None
if importlib.util.find_spec("celery") is not None:
    try:
        from .celery import app as celery_app
    except Exception:
        celery_app = None

__all__ = ('celery_app',)

if importlib.util.find_spec("MySQLdb") is None:
    import pymysql

    pymysql.install_as_MySQLdb()
