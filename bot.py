import os
import asyncio
import psycopg2
from datetime import datetime
import pytz
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID")
DATABASE_URL = os.environ.get("DATABASE_URL")

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

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


# === БАЗА ДАННЫХ ===

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id SERIAL PRIMARY KEY,
            rule TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_report (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            task_key TEXT NOT NULL,
            status BOOLEAN,
            issue TEXT,
            UNIQUE(date, task_key)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def db_add_knowledge(rule):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO knowledge (rule) VALUES (%s)", (rule,))
    conn.commit()
    cur.close()
    conn.close()


def db_get_knowledge():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT rule FROM knowledge ORDER BY created_at")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]


def db_clear_knowledge():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM knowledge")
    conn.commit()
    cur.close()
    conn.close()


def load_knowledge():
    items = db_get_knowledge()
    if items:
        return "\n\nДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА:\n" + "\n".join(f"- {x}" for x in items)
    return ""


def db_update_report(task_key, status, issue=None):
    today = datetime.now(MOSCOW_TZ).date()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily_report (date, task_key, status, issue)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (date, task_key) DO UPDATE SET status=%s, issue=%s
    """, (today, task_key, status, issue, status, issue))
    conn.commit()
    cur.close()
    conn.close()


def db_get_report():
    today = datetime.now(MOSCOW_TZ).date()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT task_key, status, issue FROM daily_report WHERE date=%s", (today,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0]: {"status": r[1], "issue": r[2]} for r in rows}


# === КЛАВИАТУРЫ ===

def make_keyboard(task_key):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Сделано", callback_data=f"done_{task_key}"),
            InlineKeyboardButton("⏰ Через 5 мин", callback_data=f"snooze_{task_key}"),
        ],
        [InlineKeyboardButton("❌ Не сделано", callback_data=f"skip_{task_key}")]
    ])


def make_yesno_keyboard(task_key):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data=f"yes_{task_key}"),
            InlineKeyboardButton("❌ Нет", callback_data=f"no_{task_key}"),
        ]
    ])


# === ВЕЧЕРНИЙ ОПРОС ===

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


# === ОТЧЁТ ===

def format_status(data, key):
    if key not in data:
        return "⬜️"
    return "✅" if data[key]["status"] else "❌"


async def send_daily_report(app):
    report = db_get_report()
    today = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y")

    text = f"📊 Отчёт за {today}\n\n"
    text += "📋 Задачи дня:\n"
    text += f"{format_status(report, 'records_tomorrow')} Записи на завтра проверены\n"
    text += f"{format_status(report, 'free_slots')} Свободные окошки опубликованы\n"
    text += f"{format_status(report, 'unconfirmed_17')} Неподтверждённые — написала в 17:00\n"
    text += f"{format_status(report, 'calls_1930')} Звонки в 19:30\n\n"
    text += "🔧 Вечерний чеклист:\n"
    text += f"{format_status(report, 'yclients_done')} Все клиенты пробиты в YClients\n"
    text += f"{format_status(report, 'checks_done')} Чеки сверены\n"
    text += f"{format_status(report, 'integrations_ok')} Интеграции работают\n"
    text += f"{format_status(report, 'systems_ok')} Все системы работают\n"

    issues = [v["issue"] for v in report.values() if v.get("issue")]
    if issues:
        text += "\n⚠️ Проблемы:\n"
        for issue in issues:
            text += f"— {issue}\n"

    if OWNER_CHAT_ID:
        await app.bot.send_message(chat_id=OWNER_CHAT_ID, text=text)


# === РАСПИСАНИЕ ===

async def schedule_reminders(app):
    await asyncio.sleep(5)
    last_sent = {}

    while True:
        now = datetime.now(MOSCOW_TZ)
        h, m = now.hour, now.minute
        key_time = f"{h}:{m}"

        if h == 10 and m == 0 and last_sent.get("r1") != key_time:
            last_sent["r1"] = key_time
            await app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="☀️ 10:00 — Проверь записи на ЗАВТРА!\n\nУслуги, цены, имена — всё корректно? Автонапоминания уйдут в 11:00.",
                reply_markup=make_keyboard("records_tomorrow")
            )

        elif h == 11 and m == 0 and last_sent.get("r2") != key_time:
            last_sent["r2"] = key_time
            await app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="📢 11:00 — Опубликуй свободные окошки в Telegram!",
                reply_markup=make_keyboard("free_slots")
            )

        elif h == 17 and m == 0 and last_sent.get("r3") != key_time:
            last_sent["r3"] = key_time
            await app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="📱 17:00 — Есть неподтверждённые записи?\nНапиши клиенту в другой мессенджер!",
                reply_markup=make_keyboard("unconfirmed_17")
            )

        elif h == 19 and m == 30 and last_sent.get("r4") != key_time:
            last_sent["r4"] = key_time
            await app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text="📞 19:30 — Неподтверждённые — ЗВОНИТЬ!\n⚠️ После 20:00 не звоним!",
                reply_markup=make_keyboard("calls_1930")
            )

        elif h == 21 and m == 30 and last_sent.get("r5") != key_time:
            last_sent["r5"] = key_time
            await app.bot.send_message(chat_id=ADMIN_CHAT_ID, text="🌙 Вечерний отчёт! Отвечай на вопросы:")
            await asyncio.sleep(2)
            await app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"❓ {EVENING_QUESTIONS['yclients_done']}",
                reply_markup=make_yesno_keyboard("yclients_done")
            )

        elif h == 22 and m == 0 and last_sent.get("r6") != key_time:
            last_sent["r6"] = key_time
            await send_daily_report(app)

        await asyncio.sleep(30)


# === ОБРАБОТЧИКИ ===

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("done_"):
        key = data[5:]
        db_update_report(key, True)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Отмечено!")

    elif data.startswith("yes_"):
        key = data[4:]
        db_update_report(key, True)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Отмечено!")
        await send_next_evening_question(context.application, key)

    elif data.startswith("no_"):
        key = data[3:]
        db_update_report(key, False)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Напиши что случилось:")
        context.user_data["waiting_issue"] = key
        await send_next_evening_question(context.application, key)

    elif data.startswith("skip_"):
        key = data[5:]
        db_update_report(key, False)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Напиши причину:")
        context.user_data["waiting_issue"] = key

    elif data.startswith("snooze_"):
        key = data[7:]
        text = query.message.text
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏰ Напомню через 5 минут!")
        await asyncio.sleep(300)
        await context.application.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🔔 Повтор!\n\n{text}",
            reply_markup=make_keyboard(key)
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text

    if context.user_data.get("waiting_issue"):
        key = context.user_data.pop("waiting_issue")
        db_update_report(key, False, issue=user_message)
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
        await update.message.reply_text("Напиши что добавить.\nПример:\n/teach Если спрашивают про парковку — есть во дворе")
        return
    rule = " ".join(context.args)
    db_add_knowledge(rule)
    await update.message.reply_text(f"✅ Запомнила навсегда: {rule}")


async def list_knowledge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = db_get_knowledge()
    if not items:
        await update.message.reply_text("База пока пустая")
        return
    text = "\n".join(f"{i+1}. {x}" for i, x in enumerate(items))
    await update.message.reply_text(f"📚 База знаний:\n\n{text}")


async def clear_knowledge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_clear_knowledge()
    await update.message.reply_text("🗑 База знаний очищена")


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("teach", "Обучить бота новому правилу"),
        BotCommand("knowledge", "Показать базу знаний"),
    ])
    init_db()
    asyncio.create_task(schedule_reminders(app))


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("teach", teach))
    app.add_handler(CommandHandler("knowledge", list_knowledge))
    app.add_handler(CommandHandler("clear", clear_knowledge))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
