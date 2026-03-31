#!/usr/bin/env python3
"""Test Telegram formatting without full bot setup"""

from telegram import Bot
import asyncio
import os

# You can put your test chat ID here (get it by messaging @userinfobot in Telegram)
TEST_CHAT_ID = "113627061"  # Replace with your actual chat ID

async def test_formatting():
    """Test different formatting options"""
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN not found in environment")
        return
    
    bot = Bot(token=bot_token)
    
    test_messages = [
        {
            "text": "**Тест жирного текста**\n*Тест курсива*\nПростой текст",
            "parse_mode": "Markdown",
            "description": "Markdown"
        },
        {
            "text": "*Тест жирного текста*\n_Тест курсива_\nПростой текст", 
            "parse_mode": "MarkdownV2",
            "description": "MarkdownV2"
        },
        {
            "text": "<b>Тест жирного текста</b>\n<i>Тест курсива</i>\nПростой текст",
            "parse_mode": "HTML",
            "description": "HTML"
        }
    ]
    
    for test in test_messages:
        try:
            print(f"Testing {test['description']}...")
            await bot.send_message(
                chat_id=TEST_CHAT_ID,
                text=test["text"], 
                parse_mode=test["parse_mode"]
            )
            print(f"SUCCESS: {test['description']} sent successfully")
        except Exception as e:
            print(f"ERROR {test['description']}: {e}")

if __name__ == "__main__":
    print("Testing Telegram formatting...")
    asyncio.run(test_formatting())