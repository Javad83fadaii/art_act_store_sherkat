import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    print("--- store_artwork ---")
    cursor.execute("DESCRIBE store_artwork")
    for row in cursor.fetchall():
        print(row)
        
    print("\n--- auction_auction ---")
    try:
        cursor.execute("DESCRIBE auction_auction")
        for row in cursor.fetchall():
            print(row)
    except Exception as e:
        print(e)

    print("\n--- action_action ---")
    try:
        cursor.execute("DESCRIBE action_action")
        for row in cursor.fetchall():
            print(row)
    except Exception as e:
        print(e)
