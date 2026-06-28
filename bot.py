import os
import anthropic
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

SYSTEM_PROMPT = """Ты — AI-помощник администратора студии эпиляции Darya Sugarya (Москва, Таганская).
Твоя задача: когда администратор Виктория присылает тебе сообщение от клиента, ты предлагаешь готовый текст ответа.

ВАЖНЫЕ ПРАВИЛА:
- Отвечай ТОЛЬКО готовым текстом для отправки клиенту
- Тон: дружелюбный, тёплый, профессиональный
- Никогда не придумывай цены
- При жалобах: сочувствие + предложить переделать бесплатно у Дарьи
- При медицинских вопросах пиши [ПЕРЕДАТЬ ДАРЬЕ]
- Если клиент отказался — не настаивай

АДРЕС: Таганская 1/2с2, подъезд 1, этаж 2, кабинет 8

ПРАЙС:
- Гл. бикини + подмышки: 2000р (Дарья: 2300р)
- Гл. бикини + подм + голени воск: 2800р (Дарья: 3100р)
- Гл. бикини + подм + голени сахар: 3100р (Дарья: 3400р)
- Гл. бикини + подм + ноги воск: 3300р (Дарья: 3700р)
- Гл. бикини + подм + ноги сахар: 3600р (Дарья: 4000р)
- Ягодицы к комплексу: +600р
- Подмышки: 500р
- Глубокое бикини: 1600р (Дарья: 1900р)
- Голени воск: 1000р, сахар: 1200р
- Ноги полностью воск: 1400р (Дарья: 1600р), сахар: 1700р (Дарья: 2000р)
- Руки 1/2 воск: 800р, сахар: 1000р
- Руки полностью воск: 1300р, сахар: 1500р
- Лазер гл.бикини + подм: 2990р
- Лазер гл.бикини + подм + голени: 4990р
- Лазер гл.бикини + подм + ноги: 5990р
- Первое посещение 3 зоны: 1990р
- Первое посещение гл.бикини + подм + ноги: 2490р
ВАЖНО: лицо лазером не делаем!"""


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.reply_text("⏳ Готовлю ответ...")
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Сообщение от клиента:\n\n{user_message}"}]
        )
        reply = response.content[0].text
        await update.message.reply_text(f"💬 Предлагаемый ответ:\n\n{reply}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен!")
    await app.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
