import importlib.util

if importlib.util.find_spec("MySQLdb") is None:
    import pymysql

    pymysql.install_as_MySQLdb()
