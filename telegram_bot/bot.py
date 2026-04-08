"""Telegram bot for FlatAgent."""

import hashlib
import logging
import asyncio
import time
import traceback
import tempfile
import os
from collections import defaultdict, deque
from typing import Dict, Any
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from langchain_core.messages import HumanMessage, AIMessage

from config import get_settings
from agent import build_graph
from agent.memory import memory_manager
from agent.tools.csv_analysis import analyze_csv

logger = logging.getLogger(__name__)

_TG_RATE_LIMIT = 20
_TG_RATE_WINDOW = 60.0
_user_timestamps: Dict[str, deque] = defaultdict(deque)


def _is_user_rate_limited(user_id: str) -> bool:
    now = time.monotonic()
    dq = _user_timestamps[user_id]
    while dq and now - dq[0] > _TG_RATE_WINDOW:
        dq.popleft()
    if len(dq) >= _TG_RATE_LIMIT:
        return True
    dq.append(now)
    return False


_s = get_settings()
agent_graph = build_graph(str(_s.db_path))



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /start command - resets long-term memory for a fresh session."""
    user_id = str(update.effective_chat.id)
    memory_manager.delete_user_facts(user_id)

    welcome_message = """Добро пожаловать! Я FlatAgent - ваш помощник по недвижимости.

Могу помочь с:
- Расчетом ипотеки - укажите сумму, ставку и срок
- Сравнением объектов - первичка vs вторичка
- Поиском информации - цены, районы, новостройки
- Консультациями - юридические вопросы, документы, советы
- Анализом CSV с объявлениями - регрессия OLS + графики + рекомендация

Просто отправьте мне ваш вопрос или CSV файл с данными о квартирах!"""

    await update.message.reply_text(welcome_message)


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /forget command - clears all stored facts about the user."""
    user_id = str(update.effective_chat.id)
    memory_manager.delete_user_facts(user_id)
    await update.message.reply_text(
        "Готово. Я забыл всё, что знал о вас. Можете начать с чистого листа."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for text messages."""
    try:
        user_message = update.message.text
        user_id = str(update.effective_chat.id)
        uid_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]

        if _is_user_rate_limited(user_id):
            logger.warning("rate limit exceeded for user %s", uid_hash)
            await update.message.reply_text(
                "Слишком много сообщений. Пожалуйста, подождите немного."
            )
            return

        from agent.input_guard import validate_user_message
        valid, reason = validate_user_message(user_message)
        if not valid:
            await update.message.reply_text(reason)
            return

        logger.info("message from %s: %s", uid_hash, user_message[:80])

        await update.message.chat.send_action(action="typing")

        config = {"configurable": {"thread_id": user_id}}

        input_state = {
            "messages": [HumanMessage(content=user_message)],
            "user_id": user_id,
            "route": None
        }

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: agent_graph.invoke(input_state, config)
        )

        ai_messages = [msg for msg in result.get("messages", []) if isinstance(msg, AIMessage)]

        if ai_messages:
            response_text = ai_messages[-1].content
            max_length = 4096

            try:
                if len(response_text) > max_length:
                    for i in range(0, len(response_text), max_length):
                        await update.message.reply_text(response_text[i:i+max_length], parse_mode='Markdown')
                else:
                    await update.message.reply_text(response_text, parse_mode='Markdown')
            except Exception as markdown_error:
                logger.warning("markdown parsing failed: %s, sending as plain text", markdown_error)
                if len(response_text) > max_length:
                    for i in range(0, len(response_text), max_length):
                        await update.message.reply_text(response_text[i:i+max_length])
                else:
                    await update.message.reply_text(response_text)
        else:
            await update.message.reply_text("Извините, произошла ошибка при обработке вашего запроса.")

    except Exception as e:
        logger.error("error processing message: %s", e)
        logger.error("traceback: %s", traceback.format_exc())
        await update.message.reply_text(
            "Произошла ошибка при обработке вашего запроса. Попробуйте еще раз."
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle uploaded documents - analyze CSV files with apartment data."""
    document = update.message.document
    if not document:
        return

    filename = document.file_name or ""
    if not filename.lower().endswith('.csv'):
        await update.message.reply_text(
            "Поддерживаются только CSV файлы. Пришлите файл с данными о квартирах."
        )
        return

    await update.message.chat.send_action(action="typing")
    await update.message.reply_text("Файл получен, анализирую данные...")

    tmp_path = None
    chart_path = None
    try:
        tg_file = await document.get_file()
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(tmp_path)

        result = analyze_csv(tmp_path)

        if result['error']:
            await update.message.reply_text(f"Ошибка анализа: {result['error']}")
            return

        summary = result['summary']
        ols_text = result['ols_text']
        recommendation = result['recommendation']
        chart_path = result['chart_path']

        full_text = f"{summary}\n\n{ols_text}\n\n{recommendation}"
        max_length = 4096
        if len(full_text) > max_length:
            full_text = full_text[:max_length - 3] + "..."

        try:
            await update.message.reply_text(full_text, parse_mode='Markdown')
        except Exception:
            await update.message.reply_text(full_text)

        if chart_path and os.path.exists(chart_path):
            with open(chart_path, 'rb') as img:
                await update.message.reply_photo(
                    photo=img,
                    caption="Графики анализа данных квартир"
                )

    except Exception as e:
        logger.error("error processing csv document: %s", e)
        logger.error(traceback.format_exc())
        await update.message.reply_text(
            "Произошла ошибка при анализе файла. Проверьте формат CSV."
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        if chart_path and os.path.exists(chart_path):
            try:
                os.unlink(chart_path)
            except Exception:
                pass


async def process_webhook(data: Dict[str, Any]) -> None:
    """Process webhook from Telegram."""
    try:
        logger.debug("webhook received: %s", data)
        bot = Bot(token=_s.telegram_bot_token)
        update = Update.de_json(data, bot)

        if update.message:
            if update.message.text:
                if update.message.text.startswith('/start'):
                    await start(update, None)
                elif update.message.text.startswith('/forget'):
                    await forget(update, None)
                else:
                    await handle_message(update, None)

    except Exception as e:
        logger.error("error processing webhook: %s", e)
        logger.error("traceback: %s", traceback.format_exc())


def start_bot_polling() -> None:
    """Start bot in polling mode."""
    if not _s.telegram_bot_token:
        logger.error("telegram bot token not provided")
        return

    try:
        application = Application.builder().token(_s.telegram_bot_token).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("forget", forget))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("telegram bot started in polling mode")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error("error starting bot: %s", e)



if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)

    logger.info("starting telegram bot")
    start_bot_polling()
