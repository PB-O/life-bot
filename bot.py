import os
import json
import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from telegram.request import HTTPXRequest
from PIL import Image, ImageDraw, ImageFont

# ==========================
# Настройки
# ==========================
import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
YOUR_USER_ID = int(os.environ["YOUR_USER_ID"])

USERS_FILE = "users.json"
BIRTHDAYS_FILE = "birthdays.json"
ACTIVE_FILE = "active_users.json"

# ==========================
# Пользовательское меню (без кнопки отписки)
# ==========================
USER_KEYBOARD = [
    ["📅 Ввести дату рождения"],
    ["🕒 Мои единицы времени", "📊 Моя статистика"]
]

# ==========================
# Загрузка и сохранение
# ==========================
def load_data():
    known_users = set()
    user_birthdays = {}
    active_users = set()

    for file, var in [(USERS_FILE, known_users), (ACTIVE_FILE, active_users)]:
        if os.path.exists(file):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    var.update(set(json.load(f)))
            except:
                pass

    if os.path.exists(BIRTHDAYS_FILE):
        try:
            with open(BIRTHDAYS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                user_birthdays.update({int(k): datetime.fromisoformat(v) for k, v in raw.items()})
        except:
            pass

    return known_users, user_birthdays, active_users

def save_all(known_users, user_birthdays, active_users):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(known_users), f)
        with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v.isoformat() for k, v in user_birthdays.items()}, f)
        with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(active_users), f)
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")

# ==========================
# Визуализация
# ==========================
def create_weeks_image(lived_weeks: int, birth_date: datetime):
    CELL_SIZE = 12
    GRID_WIDTH = 52
    LIFESPAN_YEARS = 90
    GRID_HEIGHT = LIFESPAN_YEARS
    MARGIN = 20
    TOP_PAD = 60
    BOTTOM_PAD = 60

    W = GRID_WIDTH * CELL_SIZE + 2 * MARGIN
    H = GRID_HEIGHT * CELL_SIZE + TOP_PAD + BOTTOM_PAD

    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_large = font_small = None
    try:
        font_large = ImageFont.truetype("arial.ttf", 20)
        font_small = ImageFont.truetype("arial.ttf", 12)
    except:
        try:
            font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
            font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
        except:
            pass

    age_years = (datetime.today() - birth_date).days // 365
    title = f"Ты прожил(а) {lived_weeks} недель ({age_years} лет)"
    draw.text((MARGIN, 10), title, fill=(30, 30, 30), font=font_large)

    draw.rectangle([MARGIN, 40, MARGIN + 15, 55], fill=(76, 175, 80))  # Зелёный
    draw.text((MARGIN + 20, 40), "Прожито", fill=(30, 30, 30), font=font_small)

    draw.rectangle([MARGIN + 100, 40, MARGIN + 115, 55], fill=(220, 220, 220))
    draw.text((MARGIN + 120, 40), "Осталось", fill=(30, 30, 30), font=font_small)

    total = GRID_WIDTH * GRID_HEIGHT
    lived = min(lived_weeks, total)
    for i in range(total):
        row = i // GRID_WIDTH
        col = i % GRID_WIDTH
        x0 = MARGIN + col * CELL_SIZE
        y0 = TOP_PAD + row * CELL_SIZE
        x1 = x0 + CELL_SIZE - 2
        y1 = y0 + CELL_SIZE - 2
        color = (76, 175, 80) if i < lived else (230, 230, 230)
        draw.rectangle([x0, y0, x1, y1], fill=color, outline=(245, 245, 245))

    for year in range(5, LIFESPAN_YEARS + 1, 5):
        x_center = MARGIN + (GRID_WIDTH * CELL_SIZE) // 2
        y_text = TOP_PAD + (year * CELL_SIZE) + 2
        draw.text((x_center - 8, y_text), str(year), fill=(100, 100, 100), font=font_small)
        y_line = TOP_PAD + (year * CELL_SIZE)
        draw.line([MARGIN, y_line, MARGIN + GRID_WIDTH * CELL_SIZE, y_line], fill=(200, 200, 200), width=1)

    draw.text(
        (MARGIN, H - 30),
        "1 клетка = 1 неделя жизни • Всего ~4680 недель (90 лет)",
        fill=(100, 100, 100),
        font=font_small
    )

    return img

# ==========================
# Вспомогательные функции
# ==========================
def get_days_to_birthday(birth_date: datetime):
    today = datetime.today()
    try:
        this_year_birthday = birth_date.replace(year=today.year)
    except ValueError:
        this_year_birthday = birth_date.replace(year=today.year, day=28)
    if this_year_birthday < today:
        next_birthday = this_year_birthday + relativedelta(years=1)
    else:
        next_birthday = this_year_birthday
    return (next_birthday - today).days

def get_median_age(active_users, user_birthdays):
    if not active_users:
        return 0
    ages = []
    today = datetime.today()
    for uid in active_users:
        bd = user_birthdays.get(uid)
        if bd:
            age = today.year - bd.year
            if (today.month, today.day) < (bd.month, bd.day):
                age -= 1
            ages.append(age)
    if not ages:
        return 0
    ages.sort()
    n = len(ages)
    return ages[n // 2] if n % 2 == 1 else (ages[n // 2 - 1] + ages[n // 2]) // 2

def generate_report_text(user_id: int, user_birthdays, active_users):
    birth_date = user_birthdays.get(user_id)
    if not birth_date:
        return None

    today = datetime.today()
    days = (today - birth_date).days
    weeks = days // 7
    total_weeks = 90 * 52
    percentage = min(100.0, weeks / total_weeks * 100)
    days_to_bd = get_days_to_birthday(birth_date)
    median_age = get_median_age(active_users, user_birthdays)
    user_age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        user_age -= 1

    comparison_text = ""
    if median_age > 0:
        if user_age > median_age:
            comparison_text = f"\n📊 Ты старше медианного пользователя ({median_age} лет)."
        elif user_age < median_age:
            comparison_text = f"\n📊 Ты младше медианного пользователя ({median_age} лет)."
        else:
            comparison_text = f"\n📊 Ты того же возраста, что и медианный пользователь ({median_age} лет)."

    return (
        f"✅ Твоя статистика:\n"
        f"📅 Дней: {days}\n"
        f"🗓️ Недель: {weeks} ({percentage:.1f}% при 90 годах)\n"
        f"⏳ До дня рождения: {days_to_bd} дней{comparison_text}"
    )

# ==========================
# Рассылки
# ==========================
async def send_weekly_update(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.user_id
    birth_date = context.application.bot_data.get("birthdays", {}).get(user_id)
    if not birth_date:
        return

    today = datetime.today()
    days = (today - birth_date).days
    weeks = days // 7

    img = create_weeks_image(weeks, birth_date)
    path = f"weekly_{user_id}.png"
    img.save(path)

    try:
        with open(path, "rb") as f:
            photo_data = f.read()
        await context.bot.send_message(chat_id=user_id, text=f"🔄 Обновление!\n📅 {days} дней\n🗓️ {weeks} недель")
        await context.bot.send_photo(chat_id=user_id, photo=photo_data)
    except Exception as e:
        logging.warning(f"Не отправлено {user_id}: {e}")
        known_users = context.application.bot_data.get("known_users", set())
        active_users = context.application.bot_data.get("active_users", set())
        if user_id in known_users:
            known_users.discard(user_id)
            active_users.discard(user_id)
            context.application.bot_data["known_users"] = known_users
            context.application.bot_data["active_users"] = active_users
            save_all(known_users, context.application.bot_data["birthdays"], active_users)
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass

async def check_and_send_birthday(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.user_id
    birth_date = context.application.bot_data.get("birthdays", {}).get(user_id)
    if not birth_date:
        return

    today = datetime.today()
    if birth_date.month == 2 and birth_date.day == 29:
        is_leap = (today.year % 4 == 0 and (today.year % 100 != 0 or today.year % 400 == 0))
        if today.month == 2 and today.day == 28 and not is_leap:
            pass
        elif today.month == 2 and today.day == 29 and is_leap:
            pass
        else:
            return
    else:
        if not (today.month == birth_date.month and today.day == birth_date.day):
            return

    age = today.year - birth_date.year
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 С Днём Рождения!\nТебе исполняется {age} лет! 🎂\nПусть каждый день будет наполнен смыслом."
        )
    except Exception as e:
        logging.warning(f"Не удалось поздравить {user_id}: {e}")

def schedule_birthday_greeting(job_queue, user_id, birth_date):
    if job_queue is None:
        return
    for job in job_queue.get_jobs_by_name(f"birthday_{user_id}"):
        job.schedule_removal()
    job_queue.run_daily(
        check_and_send_birthday,
        time=datetime.strptime("08:00", "%H:%M").time(),
        user_id=user_id,
        name=f"birthday_{user_id}"
    )

def schedule_weekly_update(job_queue, user_id, birth_date):
    if job_queue is None:
        return
    for job in job_queue.get_jobs_by_name(f"weekly_{user_id}"):
        job.schedule_removal()
    job_queue.run_daily(
        send_weekly_update,
        time=datetime.strptime("09:00", "%H:%M").time(),
        days=(birth_date.weekday(),),
        user_id=user_id,
        name=f"weekly_{user_id}"
    )

# ==========================
# Обработчики
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    known_users = context.application.bot_data["known_users"]
    known_users.add(user_id)
    context.application.bot_data["known_users"] = known_users
    save_all(known_users, context.application.bot_data["birthdays"], context.application.bot_data["active_users"])

    reply_markup = ReplyKeyboardMarkup(USER_KEYBOARD, resize_keyboard=True)
    await update.message.reply_text(
        "Привет! 🌟 Я помогу тебе осознать время.\n\n"
        "Используй кнопки ниже 👇\n"
        "Чтобы отписаться от рассылок — отправь /stop",
        reply_markup=reply_markup
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    known_users = context.application.bot_data["known_users"]
    active_users = context.application.bot_data["active_users"]
    birthdays = context.application.bot_data["birthdays"]

    if user_id in known_users:
        known_users.discard(user_id)
        active_users.discard(user_id)
        birthdays.pop(user_id, None)
        context.application.bot_data["known_users"] = known_users
        context.application.bot_data["active_users"] = active_users
        context.application.bot_data["birthdays"] = birthdays
        save_all(known_users, birthdays, active_users)

        if context.job_queue:
            for name in [f"weekly_{user_id}", f"birthday_{user_id}"]:
                for job in context.job_queue.get_jobs_by_name(name):
                    job.schedule_removal()
        await update.message.reply_text("✅ Ты отписался(ась).")
    else:
        await update.message.reply_text("Ты не подписан.")

async def time_units(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    birth = context.application.bot_data["birthdays"].get(user_id)
    if not birth:
        await update.message.reply_text("Сначала введи дату рождения через кнопку 📅!")
        return

    days = (datetime.today() - birth).days
    hours = days * 24
    minutes = hours * 60
    seconds = minutes * 60

    await update.message.reply_text(
        f"⏳ Ты существуешь:\n"
        f"📅 {days} дней\n"
        f"🕒 {hours:,} часов\n"
        f"⏱️ {minutes:,} минут\n"
        f"💫 {seconds:,} секунд"
    )

async def show_my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    report = generate_report_text(user_id, context.application.bot_data["birthdays"], context.application.bot_data["active_users"])
    if not report:
        await update.message.reply_text("Сначала введи дату рождения через кнопку 📅!")
        return

    await update.message.reply_text(report)
    birth_date = context.application.bot_data["birthdays"][user_id]
    weeks = (datetime.today() - birth_date).days // 7
    img = create_weeks_image(weeks, birth_date)
    path = f"stats_{user_id}.png"
    img.save(path)

    try:
        with open(path, "rb") as f:
            photo_data = f.read()
        await update.message.reply_photo(photo=photo_data)
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "🕒 Мои единицы времени":
        await time_units(update, context)
        return
    elif text == "📊 Моя статистика":
        await show_my_stats(update, context)
        return
    elif text == "📅 Ввести дату рождения":
        await update.message.reply_text("Введите дату рождения в формате ДД.ММ.ГГГГ\nПример: 05.03.1998")
        return

    known_users = context.application.bot_data["known_users"]
    known_users.add(user_id)
    context.application.bot_data["known_users"] = known_users

    clean = text.replace("/", ".").strip()
    parts = clean.split(".")
    if len(parts) != 3:
        await update.message.reply_text("❌ Формат: ДД.ММ.ГГГГ")
        return

    try:
        day, month, year = map(int, parts)
        if not (1900 <= year <= datetime.today().year):
            raise ValueError()
        if not (1 <= month <= 12):
            raise ValueError()
        if not (1 <= day <= 31):
            raise ValueError()

        birth_date = datetime(year, month, day)
        if birth_date > datetime.today():
            await update.message.reply_text("📅 Дата не может быть в будущем!")
            return

        birthdays = context.application.bot_data["birthdays"]
        active_users = context.application.bot_data["active_users"]
        birthdays[user_id] = birth_date
        active_users.add(user_id)
        context.application.bot_data["birthdays"] = birthdays
        context.application.bot_data["active_users"] = active_users
        save_all(known_users, birthdays, active_users)

        schedule_weekly_update(context.job_queue, user_id, birth_date)
        schedule_birthday_greeting(context.job_queue, user_id, birth_date)

        report = generate_report_text(user_id, birthdays, active_users)
        await update.message.reply_text(report)

        img = create_weeks_image((datetime.today() - birth_date).days // 7, birth_date)
        path = f"result_{user_id}.png"
        img.save(path)

        try:
            with open(path, "rb") as f:
                photo_data = f.read()
            await update.message.reply_photo(photo=photo_data)
        finally:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass

    except (ValueError, OverflowError):
        await update.message.reply_text("❌ Не удалось распознать дату. Пример: 01.01.2000")

# ==========================
# Админ-панель
# ==========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return
    keyboard = [
        [InlineKeyboardButton("📨 Отправить рассылку", callback_data='admin_broadcast')],
        [InlineKeyboardButton("📊 Посмотреть статистику", callback_data='admin_stats')],
        [InlineKeyboardButton("📤 Выгрузить список", callback_data='admin_export')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Панель администратора:", reply_markup=reply_markup)

async def admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    known_users = context.application.bot_data["known_users"]
    active_users = context.application.bot_data["active_users"]
    birthdays = context.application.bot_data["birthdays"]

    if data == 'admin_broadcast':
        await query.message.reply_text("Отправь сообщение для рассылки (текст или фото с подписью).")
        context.user_data['admin_mode'] = 'broadcast'
    elif data == 'admin_stats':
        total = len(known_users)
        active = len(active_users)
        median = get_median_age(active_users, birthdays)
        await query.message.reply_text(
            f"👥 Всего пользователей: {total}\n"
            f"✅ Активных (ввели дату): {active}\n"
            f"🔢 Медианный возраст: {median} лет"
        )
    elif data == 'admin_export':
        with open("export_users.txt", "w", encoding="utf-8") as f:
            for uid in known_users:
                f.write(f"{uid}\n")
        await query.message.reply_document(document=open("export_users.txt", "rb"))
        os.remove("export_users.txt")

async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != YOUR_USER_ID:
        return
    if context.user_data.get('admin_mode') != 'broadcast':
        return

    context.user_data['admin_mode'] = None
    known_users = context.application.bot_data["known_users"]

    if update.message.photo:
        caption = update.message.caption or "Сообщение от бота"
        photo_file = await update.message.photo[-1].get_file()
        photo_path = "admin_broadcast.jpg"
        await photo_file.download_to_drive(photo_path)

        try:
            with open(photo_path, "rb") as f:
                photo_data = f.read()

            success = failed = 0
            for uid in list(known_users):
                try:
                    await context.bot.send_photo(chat_id=uid, photo=photo_data, caption=caption)
                    success += 1
                except:
                    known_users.discard(uid)
                    failed += 1
            context.application.bot_data["known_users"] = known_users
            save_all(known_users, context.application.bot_data["birthdays"], context.application.bot_data["active_users"])
        finally:
            if os.path.exists(photo_path):
                try:
                    os.remove(photo_path)
                except:
                    pass

        await update.message.reply_text(f"🖼️ Отправлено: {success}, ошибок: {failed}")
    else:
        text = update.message.text
        success = failed = 0
        for uid in list(known_users):
            try:
                await context.bot.send_message(chat_id=uid, text=text)
                success += 1
            except:
                known_users.discard(uid)
                failed += 1
        context.application.bot_data["known_users"] = known_users
        save_all(known_users, context.application.bot_data["birthdays"], context.application.bot_data["active_users"])
        await update.message.reply_text(f"✅ Отправлено: {success}, ошибок: {failed}")

# ==========================
# Запуск
# ==========================
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise ValueError("❗ Замени BOT_TOKEN на токен от @BotFather")
    if YOUR_USER_ID == 123456789:
        raise ValueError("❗ Замени YOUR_USER_ID на свой ID из @userinfobot")

    known_users, user_birthdays, active_users = load_data()

    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=20.0
    )

    app = Application.builder().token(BOT_TOKEN).request(request).get_updates_request(request).build()

    app.bot_data["known_users"] = known_users
    app.bot_data["birthdays"] = user_birthdays
    app.bot_data["active_users"] = active_users

    # ✅ КРИТИЧЕСКИ ВАЖНЫЙ ПОРЯДОК ОБРАБОТЧИКОВ
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("time_units", time_units))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(MessageHandler(filters.TEXT & filters.User(YOUR_USER_ID), admin_message_handler))
    app.add_handler(MessageHandler(filters.PHOTO & filters.User(YOUR_USER_ID), admin_message_handler))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.User(YOUR_USER_ID),
        handle_message
    ))

    app.add_handler(CallbackQueryHandler(admin_button))

    print("✅ Бот запущен. Команды работают. Зелёные клетки. Разбивка по 5 годам.")
    app.run_polling()

# ==========================
# ОДИНОЧНЫЙ ЗАПУСК — БЕЗ ЦИКЛА
# ==========================
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Бот остановлен вручную.")
    except Exception as e:
        logging.exception("Критическая ошибка:")

        print(f"❌ Бот упал: {e}")


