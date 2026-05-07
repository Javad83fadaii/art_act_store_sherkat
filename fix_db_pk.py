import os
import django
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

with connection.cursor() as cursor:
    try:
        # Disable FK checks to allow altering PK
        cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
        
        # Alter store_artwork ID to bigint
        print("Altering store_artwork.id to BIGINT...")
        cursor.execute("ALTER TABLE store_artwork MODIFY id bigint NOT NULL AUTO_INCREMENT;")
        
        cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
        print("Successfully altered store_artwork.id")
    except Exception as e:
        print(f"Error: {e}")
