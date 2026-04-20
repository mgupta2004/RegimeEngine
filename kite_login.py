import os
import webbrowser
from kiteconnect import KiteConnect
from dotenv import load_dotenv, set_key

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_FILE)

API_KEY = os.environ.get("KITE_API_KEY", "")

if not API_KEY:
    API_KEY = input("Enter your Kite API Key: ").strip()
    set_key(ENV_FILE, "KITE_API_KEY", API_KEY)

kite = KiteConnect(api_key=API_KEY)
login_url = kite.login_url()

print(f"\nOpening Kite login URL...\n{login_url}\n")
webbrowser.open(login_url)

request_token = input("Paste the request_token from the redirect URL: ").strip()

session = kite.generate_session(request_token, api_secret=os.environ.get("KITE_API_SECRET", ""))
access_token = session["access_token"]

set_key(ENV_FILE, "KITE_ACCESS_TOKEN", access_token)
print(f"\nAccess token saved to {ENV_FILE}")
print(f"Token: {access_token[:8]}...")
