import os
import json
import anthropic
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TEACH_FILE = "knowledge.json"

BASE_PROMPT = """Ты — помощник администратора студии эпиляции Darya Sugarya (Москва, Таганская).
Когда получаешь сообщение от клиента — пиши готовый ответ. Без предисловий, без "конечно", "отличный вопрос" и подобного. Сразу по делу.

Тон: тёплый, живой, как пишет человек. Никакого канцелярита.
При жалобах: сочувствие + предложи переделать бесплатно у Дарьи.
При медицинских вопросах — пиши [ПЕРЕДАТЬ ДАРЬЕ] в начале.
Если клиент отказался — не настаивай.
Для записи всегда давай ссылку: https://n2253459.yclients.com/

АДРЕС: Таганская 1/2с2, подъезд 1 (со стороны дороги), этаж 2, кабинет 8

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
- Ягодицы: 600р
- Зона лица: 400р
- Живот: 600р
- Поясница: 500р
- Спина: 1300р
- Лазер гл.бикини: 2300р
- Лазер гл.бикини + подм: 2990р
- Лазер гл.бикини + подм + голени: 4990р
- Лазер гл.бикини + подм + ноги: 5990р
- Лазер гл.бикини + подм + ноги + руки: 7490р
- Первое посещение 3 зоны: 1990р
- Первое посещение гл.бикини + подм + ноги: 2490р
- Абонемент гл.бикини + подм: 7990р
- Абонемент гл.бикини + подм + голени: 11990р
- Абонемент гл.бикини + подм + ноги: 13990р
ВАЖНО: лицо лазером не делаем! Ягодицы — отдельная зона, не входит в комплекс."""


def load_knowledge():
    if os.path.exists(TEACH_FILE):
        with open(TEACH_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
            return "\n\nДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА:\n" + "\n".join(f"- {x}" for x in items)
    return ""


def save_knowledge(item):
    items = []
    if os.path.exists(TEACH_FILE):
        with open(TEACH_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
    items.append(item)
    with open(TEACH_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.reply_text("⏳")
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        full_prompt = BASE_PROMPT + load_knowledge()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=full_prompt,
            messages=[{"role": "user", "content": f"Сообщение от клиента:\n\n{user_message}"}]
        )
        reply = response.content[0].text
        await update.message.reply_text(f"💬 {reply}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def teach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Напиши что добавить. Например:\n/teach Если спрашивают про парковку — отвечать: есть парковка во дворе")
        return
    item = " ".join(context.args)
    save_knowledge(item)
    await update.message.reply_text(f"✅ Запомнила: {item}")


async def list_knowledge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(TEACH_FILE):
        await update.message.reply_text("База пока пустая")
        return
    with open(TEACH_FILE, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not items:
        await update.message.reply_text("База пока пустая")
        return
    text = "\n".join(f"{i+1}. {x}" for i, x in enumerate(items))
    await update.message.reply_text(f"📚 База знаний:\n\n{text}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("teach", teach))
    app.add_handler(CommandHandler("knowledge", list_knowledge))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
