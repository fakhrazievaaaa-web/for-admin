import os
import json
import asyncio
from datetime import datetime, timedelta
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # Chat ID Виктории
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID")  # Chat ID Дарьи
TEACH_FILE = "knowledge.json"
REPORT_FILE = "daily_report.json"

BASE_PROMPT = """Ты — помощник администратора студии эпиляции Darya Sugarya (Москва, Таганская).
Когда получаешь сообщение от клиента — пиши готовый ответ. Без предисловий, сразу по делу.

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
- Ягодицы: 600р, Зона лица: 400р, Живот: 600р, Поясница: 500р, Спина: 1300р
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
ВАЖНО: лицо лазером не делаем! Ягодицы — отдельная зона."""


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


def init_report():
    report = {
        "date": datetime.now().strftime("%d.%m.%Y"),
        "tasks": {
            "records_tomorrow": None,
            "free_slots": None,
            "unconfirmed_17": None,
            "calls_1930": None,
        },
        "evening": {
            "yclients_done": None,
            "checks_done": None,
            "integrations_ok": None,
            "systems_ok": None,
        },
        "issues": []
    }
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False)


def update_report(key, section, value, issue=None):
    if not os.path.exists(REPORT_FILE):
        init_report()
    with open(REPORT_FILE, "r", encoding="utf-8") as f:
        report = json.load(f)
    report[section][key] = value
    if issue:
        report["issues"].append(issue)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False)


def get_report():
    if not os.path.exists(REPORT_FILE):
        return None
    with open(REPORT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def format_status(value):
    if value is True:
        return "✅"
    elif value is False:
        return "❌"
    return "⬜️"


def make_keyboard(task_key):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Сделано", callback_data=f"done_{task_key}"),
            InlineKeyboardButton("⏰ Напомни через 5 мин", callback_data=f"snooze_{task_key}"),
        ],
        [
            InlineKeyboardButton("❌ Не сделано", callback_data=f"skip_{task_key}"),
        ]
    ])


def make_yesno_keyboard(task_key):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data=f"yes_{task_key}"),
            InlineKeyboardButton("❌ Нет", callback_data=f"no_{task_key}"),
        ]
    ])


async def send_reminder(app, text, task_key, section="tasks"):
    if not ADMIN_CHAT_ID:
        return
    kb = make_keyboard(task_key) if section == "tasks" else make_yesno_keyboard(task_key)
    await app.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, reply_markup=kb)


async def send_daily_report(app):
    report = get_report()
    if not report or not OWNER_CHAT_ID:
        return

    t = report["tasks"]
    e = report["evening"]
    issues = report.get("issues", [])

    text = f"📊 Отчёт за {report['date']}\n\n"
    text += "📋 Задачи дня:\n"
    text += f"{format_status(t['records_tomorrow'])} Записи на завтра проверены\n"
    text += f"{format_status(t['free_slots'])} Свободные окошки опубликованы\n"
    text += f"{format_status(t['unconfirmed_17'])} Неподтверждённые — написала в 17:00\n"
    text += f"{format_status(t['calls_1930'])} Звонки в 19:30\n\n"
    text += "🔧 Вечерний чеклист:\n"
    text += f"{format_status(e['yclients_done'])} Все клиенты пробиты в YClients\n"
    text += f"{format_status(e['checks_done'])} Чеки сверены\n"
    text += f"{format_status(e['integrations_ok'])} Интеграции работают\n"
    text += f"{format_status(e['systems_ok'])} Все системы работают\n"

    if issues:
        text += "\n⚠️ Проблемы:\n"
        for issue in issues:
            text += f"— {issue}\n"

    await app.bot.send_message(chat_id=OWNER_CHAT_ID, text=text)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("done_"):
        key = data[5:]
        section = "evening" if key in ["yclients_done", "checks_done", "integrations_ok", "systems_ok"] else "tasks"
        update_report(key, section, True)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Отмечено!")

    elif data.startswith("yes_"):
        key = data[4:]
        update_report(key, "evening", True)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Отмечено!")
        await send_next_evening_question(context.application, key)

    elif data.startswith("no_"):
        key = data[3:]
        update_report(key, "evening", False)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Напиши что случилось:")
        context.user_data["waiting_issue"] = key
        await send_next_evening_question(context.application, key)

    elif data.startswith("skip_"):
        key = data[5:]
        section = "evening" if key in ["yclients_done", "checks_done", "integrations_ok", "systems_ok"] else "tasks"
        update_report(key, section, False)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Напиши причину:")
        context.user_data["waiting_issue"] = key

    elif data.startswith("snooze_"):
        key = data[7:]
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏰ Напомню через 5 минут!")
        await asyncio.sleep(300)
        text = query.message.text
        await context.application.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🔔 Повтор!\n\n{text}",
            reply_markup=make_keyboard(key)
        )


EVENING_ORDER = ["yclients_done", "checks_done", "integrations_ok", "systems_ok"]
EVENING_QUESTIONS = {
    "yclients_done": "Все клиенты пробиты в YClients?",
    "checks_done": "Чеки сверены с мастером?",
    "integrations_ok": "Интеграции работают корректно?",
    "systems_ok": "Все системы работают (Telegram, WhatsApp, Max)?",
}


async def send_next_evening_question(app, current_key):
    if current_key not in EVENING_ORDER:
        return
    idx = EVENING_ORDER.index(current_key)
    if idx + 1 < len(EVENING_ORDER):
        next_key = EVENING_ORDER[idx + 1]
        await asyncio.sleep(2)
        await app.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"❓ {EVENING_QUESTIONS[next_key]}",
            reply_markup=make_yesno_keyboard(next_key)
        )


async def schedule_reminders(app):
    await asyncio.sleep(5)
    while True:
        now = datetime.now()
        h, m = now.hour, now.minute

        if h == 10 and m == 0:
            init_report()
            await send_reminder(app,
                "☀️ 10:00 — Проверь записи на ЗАВТРА до 11:00!\n\nУслуги, цены, имена клиентов — всё корректно? Автонапоминания уйдут в 11:00.",
                "records_tomorrow")

        elif h == 11 and m == 0:
            await send_reminder(app,
                "📢 11:00 — Опубликуй свободные окошки в Telegram!\n\nПосмотри расписание и выложи доступное время.",
                "free_slots")

        elif h == 17 and m == 0:
            await send_reminder(app,
                "📱 17:00 — Есть неподтверждённые записи на сегодня?\n\nНапиши клиенту в другой мессенджер!",
                "unconfirmed_17")

        elif h == 19 and m == 30:
            await send_reminder(app,
                "📞 19:30 — Неподтверждённые записи — ЗВОНИТЬ!\n\n⚠️ После 20:00 не звоним!",
                "calls_1930")

        elif h == 21 and m == 30:
            await app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="🌙 Время вечернего отчёта! Отвечай на вопросы:",
            )
            await asyncio.sleep(2)
            await app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"❓ {EVENING_QUESTIONS['yclients_done']}",
                reply_markup=make_yesno_keyboard("yclients_done")
            )

        elif h == 22 and m == 0:
            await send_daily_report(app)

        await asyncio.sleep(60)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text

    if context.user_data.get("waiting_issue"):
        key = context.user_data.pop("waiting_issue")
        update_report(key,
                      "evening" if key in EVENING_ORDER else "tasks",
                      False,
                      issue=f"{key}: {user_message}")
        await update.message.reply_text("📝 Записала в отчёт")
        return

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
        await update.message.reply_text("Напиши что добавить.\nПример: /teach Если спрашивают про парковку — есть во дворе")
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


async def post_init(app):
    asyncio.create_task(schedule_reminders(app))


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("teach", teach))
    app.add_handler(CommandHandler("knowledge", list_knowledge))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
