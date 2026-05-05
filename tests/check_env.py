from dotenv import load_dotenv
import os
load_dotenv()
url = os.getenv("DATABASE_URL")
print(f"URL length: {len(url) if url else 0}")
print(f"URL starts with postgresql://: {url.startswith('postgresql://') if url else False}")
print(f"Contains 'hidden': { 'hidden' in url if url else False }") # Phải là False