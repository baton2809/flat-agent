"""Test API endpoint directly."""

import requests
import json

def test_api_chat():
    """Test chat API endpoint."""
    url = "http://localhost:8000/api/v1/chat"

    payload = {
        "message": "Привет! Помоги с ипотекой на 5 млн рублей под 15% на 20 лет",
        "user_id": "test_user_api"
    }

    try:
        print("Testing API endpoint...")
        print(f"Request: {payload}")

        response = requests.post(url, json=payload, timeout=30)

        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")

        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('response', 'No response')}")
            return True
        else:
            print(f"Error: {response.status_code}")
            return False

    except Exception as e:
        print(f"Request failed: {e}")
        return False

if __name__ == "__main__":
    test_api_chat()
