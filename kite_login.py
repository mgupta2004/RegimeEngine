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
print(f"Token: {access_token[:8]}...")import os
import webbrowser
from kiteconnect import KiteConnect
from dotenv import load_dotenv, set_key
import requests, json, pyotp
from urllib.parse import urlparse
from urllib.parse import parse_qs

def login():
    http_session = requests.Session()
    url = http_session.get(url='https://kite.trade/connect/login?v=3&api_key='+api_key).url
    response = http_session.post(url='https://kite.zerodha.com/api/login', data={'user_id':user_id, 'password':user_password})
    resp_dict = json.loads(response.content)
    http_session.post(url='https://kite.zerodha.com/api/twofa', data={'user_id':user_id, 'request_id':resp_dict["data"]["request_id"], 'twofa_value':pyotp.TOTP(totp_key).now()})

    url = url + "&skip_session=true"
    print(url)
    response = http_session.get(url=url, allow_redirects=True).url
    print(response)
    request_token = parse_qs(urlparse(response).query)['request_token'][0]

    kite = KiteConnect(api_key=api_key)
    data = kite.generate_session(request_token, api_secret=api_secret)
    kite.set_access_token(data["access_token"])

    return kite

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_FILE)

# API_KEY = os.environ.get("KITE_API_KEY", "")

# if not API_KEY:
#     API_KEY = input("Enter your Kite API Key: ").strip()
#     set_key(ENV_FILE, "KITE_API_KEY", API_KEY)


api_key = os.environ.get("api_key", "")
api_secret = os.environ.get("api_secret", "")
user_id = os.environ.get("user_id", "")
user_password = os.environ.get("user_password", "")
totp_key = os.environ.get("totp_key", "")

print(api_key, api_secret, user_id, user_password, totp_key)
print(pyotp.TOTP(totp_key).now())
kite = login()

access_token = kite.access_token
print(access_token)

# kite = KiteConnect(api_key=API_KEY)
# login_url = kite.login_url()

# print(f"\nOpening Kite login URL...\n{login_url}\n")
# webbrowser.open(login_url)

# request_token = input("Paste the request_token from the redirect URL: ").strip()

# session = kite.generate_session(request_token, api_secret=os.environ.get("KITE_API_SECRET", ""))
# access_token = session["access_token"]

set_key(ENV_FILE, "KITE_ACCESS_TOKEN", access_token)
print(f"\nAccess token saved to {ENV_FILE}")
print(f"Token: {access_token[:8]}...")

