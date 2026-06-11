import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print("URL:", url)
print("Key starts:", key[:10] if key else "None")

if not url or not key:
    print("Missing environment variables")
else:
    try:
        create_client(url, key)
        print("Connection successful")
    except Exception as e:
        print("Error:", e)
