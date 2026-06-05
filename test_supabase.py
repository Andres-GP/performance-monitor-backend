import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print("URL:", url)
print("Key starts:", key[:10] if key else "None")

if not url or not key:
    print("Faltan variables de entorno")
else:
    try:
        supabase = create_client(url, key)
        # Intenta leer de una tabla existente (ej. strategy_configs) o simplemente obtén el status
        print("Conexión exitosa")
    except Exception as e:
        print("Error:", e)