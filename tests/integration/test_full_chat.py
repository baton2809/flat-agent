"""Test full GigaChat chat API."""

import requests
import os
from dotenv import load_dotenv

load_dotenv()

GIGACHAT_CREDENTIALS = os.getenv('GIGACHAT_CREDENTIALS')
GIGACHAT_SCOPE = os.getenv('GIGACHAT_SCOPE')

print("-" * 50)
print("Testing full GigaChat chat flow")
print("-" * 50)

print("1. Getting access token...")
auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
auth_payload = {'scope': GIGACHAT_SCOPE}
auth_headers = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'Accept': 'application/json',
    'RqUID': '5d5ba01e-e2e4-4ff5-951b-90ad84f66311',
    'Authorization': f'Basic {GIGACHAT_CREDENTIALS}'
}

auth_response = requests.post(auth_url, headers=auth_headers, data=auth_payload, verify=False)
print(f"Auth status: {auth_response.status_code}")

if auth_response.status_code != 200:
    print(f"Auth failed: {auth_response.text}")
    exit(1)

access_token = auth_response.json()['access_token']
print("Access token received")

print("\n2. Testing chat API...")
chat_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
chat_headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {access_token}'
}

chat_payload = {
    "model": "GigaChat",
    "messages": [
        {"role": "user", "content": "Привет! Помоги рассчитать ипотеку на 5 миллионов рублей под 15% на 20 лет"}
    ],
    "temperature": 0.7
}

chat_response = requests.post(chat_url, headers=chat_headers, json=chat_payload, verify=False)
print(f"Chat status: {chat_response.status_code}")

if chat_response.status_code == 200:
    response_data = chat_response.json()
    reply = response_data['choices'][0]['message']['content']
    print(f"GigaChat response: {reply}")
elif chat_response.status_code == 402:
    print("402 Payment Required - exceeded limit or payment required")
    print(f"Response: {chat_response.text}")
else:
    print(f"Chat failed with status {chat_response.status_code}")
    print(f"Response: {chat_response.text}")
