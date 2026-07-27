import csv
import io
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
CONSULTATION_URL = os.getenv(
    "CONSULTATION_URL", "https://t.me/visadesk_consult"
).strip()
BRAND_NAME = os.getenv("BRAND_NAME", "آوا").strip()
DB_PATH = os.getenv("DB_PATH", "data/leads.db").strip()

(
    DESTINATION,
    AGE,
    EDUCATION,
    GPA,
    LANGUAGE,
    GAP,
    FUNDS,
    REFUSAL,
    PHONE,
) = range(9)

DESTINATIONS = {
    "uk": "انگلستان",
    "germany": "آلمان",
    "italy": "ایتالیا",
    "france": "فرانسه",
    "austria": "اتریش",
    "sweden": "سوئد",
}

QUESTIONS = {
    AGE: ("سن شما؟", ["زیر ۲۴", "۲۴ تا ۲۹", "۳۰ تا ۳۴", "۳۵ تا ۳۹", "۴۰ سال به بالا"]),
    EDUCATION: ("آخرین مدرک تحصیلی؟", ["دیپلم", "کاردانی", "کارشناسی", "کارشناسی ارشد", "دکتری"]),
    GPA: ("وضعیت معدل شما؟", ["عالی +17", "خوب 15-17", "متوسط 13-15", "ضعیف زیر13"]),
    LANGUAGE: ("وضعیت مدرک زبان؟", ["مدرک معتبر با نمره خوب +ب2", "مدرک با نمره متوسط ب1", "در حال آماده‌سازی", "بدون مدرک زبان"]),
    GAP: ("فاصله تحصیلی یا گپ شما؟", ["کمتر از ۲ سال", "۲ تا ۴ سال", "۵ تا ۷ سال", "بیشتر از ۷ سال"]),
    FUNDS: ("وضعیت تمکن مالی؟", ["کامل و قابل اثبات", "نسبتاً مناسب", "نیازمند تکمیل", "فعلاً آماده نیست"]),
    REFUSAL: ("سابقه ریجکتی ویزا دارید؟", ["خیر", "بله، یک بار", "بله، بیش از یک بار"]),
}

SCORES = {
    AGE: {"زیر ۲۴": 14, "۲۴ تا ۲۹": 15, "۳۰ تا ۳۴": 12, "۳۵ تا ۳۹": 8, "۴۰ سال به بالا": 4},
    EDUCATION: {"دیپلم": 8, "کاردانی": 7, "کارشناسی": 12, "کارشناسی ارشد": 13, "دکتری": 11},
    GPA: {"عالی": 15, "خوب": 12, "متوسط": 8, "ضعیف": 3},
    LANGUAGE: {"مدرک معتبر با نمره خوب": 18, "مدرک با نمره متوسط": 13, "در حال آماده‌سازی": 7, "بدون مدرک زبان": 1},
    GAP: {"کمتر از ۲ سال": 14, "۲ تا ۴ سال": 11, "۵ تا ۷ سال": 7, "بیشتر از ۷ سال": 2},
    FUNDS: {"کامل و قابل اثبات": 17, "نسبتاً مناسب": 12, "نیازمند تکمیل": 6, "فعلاً آماده نیست": 0},
    REFUSAL: {"خیر": 7, "بله، یک بار": 3, "بله، بیش از یک بار": 0},
}

DESTINATION_ADJUSTMENT = {
    "uk": 0,
    "germany": -1,
    "italy": 2,
    "france": 1,
    "austria": -1,
    "sweden": -2,
}


def db_connect():
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                destination TEXT,
                age TEXT,
                education TEXT,
                gpa TEXT,
                language TEXT,
                study_gap TEXT,
                funds TEXT,
                refusal TEXT,
                score INTEGER,
                result_level TEXT,
                referred_by INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()


def upsert_start_user(user, referred_by=None):
    now = datetime.now(timezone.utc).isoformat()
    with db_connect() as conn:
        existing = conn.execute(
            "SELECT telegram_id, referred_by FROM leads WHERE telegram_id = ?",
            (user.id,),
        ).fetchone()
        if existing:
            if referred_by and not existing["referred_by"] and referred_by != user.id:
                conn.execute(
                    "UPDATE leads SET referred_by = ?, updated_at = ? WHERE telegram_id = ?",
                    (referred_by, now, user.id),
                )
        else:
            conn.execute(
                """
                INSERT INTO leads
                (telegram_id, username, full_name, referred_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user.id,
                    user.username or "",
                    user.full_name or "",
                    referred_by if referred_by != user.id else None,
                    now,
                    now,
                ),
            )
        conn.commit()


def save_result(user, data, score, level):
    now = datetime.now(timezone.utc).isoformat()
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO leads (
                telegram_id, username, full_name, phone, destination, age,
                education, gpa, language, study_gap, funds, refusal,
                score, result_level, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                phone=excluded.phone,
                destination=excluded.destination,
                age=excluded.age,
                education=excluded.education,
                gpa=excluded.gpa,
                language=excluded.language,
                study_gap=excluded.study_gap,
                funds=excluded.funds,
                refusal=excluded.refusal,
                score=excluded.score,
                result_level=excluded.result_level,
                updated_at=excluded.updated_at
            """,
            (
                user.id,
                user.username or "",
                user.full_name or "",
                data.get("phone", ""),
                DESTINATIONS.get(data.get("destination"), data.get("destination", "")),
                data.get("age", ""),
                data.get("education", ""),
                data.get("gpa", ""),
                data.get("language", ""),
                data.get("gap", ""),
                data.get("funds", ""),
                data.get("refusal", ""),
                score,
                level,
                now,
                now,
            ),
        )
        conn.commit()


def keyboard_from_options(options, prefix):
    rows = []
    for option in options:
        rows.append([InlineKeyboardButton(option, callback_data=f"{prefix}|{option}")])
    return InlineKeyboardMarkup(rows)


def calculate_score(data):
    score = 0
    mapping = {
        AGE: data["age"],
        EDUCATION: data["education"],
        GPA: data["gpa"],
        LANGUAGE: data["language"],
        GAP: data["gap"],
        FUNDS: data["funds"],
        REFUSAL: data["refusal"],
    }
    for state, answer in mapping.items():
        score += SCORES[state].get(answer, 0)
    score += DESTINATION_ADJUSTMENT.get(data["destination"], 0)
    return max(0, min(100, score))


def score_level(score):
    if score >= 76:
        return "پرونده اولیه قوی", "🟢"
    if score >= 58:
        return "قابل اقدام، با نیاز به بهینه‌سازی", "🟡"
    if score >= 40:
        return "ریسک متوسط رو به بالا", "🟠"
    return "فعلاً پرریسک", "🔴"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = None
    if context.args and context.args[0].startswith("ref_"):
        raw = context.args[0].replace("ref_", "", 1)
        if raw.isdigit():
            referred_by = int(raw)

    upsert_start_user(user, referred_by)
    context.user_data.clear()

    text = (
        f"سلام {user.first_name or ''} 👋\n\n"
        f"این ابزار، شرایط اولیه شما را برای پرونده تحصیلی بررسی می‌کند.\n"
        f"نتیجه صرفاً ارزیابی مقدماتی است و تضمین صدور ویزا نیست.\n\n"
        f"برای شروع روی دکمه زیر بزنید."
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("شروع ارزیابی رایگان", callback_data="begin")]]
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard)
    else:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard)
    return DESTINATION


async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    buttons = [
        InlineKeyboardButton(name, callback_data=f"destination|{key}")
        for key, name in DESTINATIONS.items()
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    await query.edit_message_text(
        "کشور مقصد موردنظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return DESTINATION


async def destination_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, key = query.data.split("|", 1)
    context.user_data["destination"] = key
    question, options = QUESTIONS[AGE]
    await query.edit_message_text(question, reply_markup=keyboard_from_options(options, "age"))
    return AGE


async def generic_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    prefix, answer = query.data.split("|", 1)

    state_map = {
        "age": ("age", EDUCATION),
        "education": ("education", GPA),
        "gpa": ("gpa", LANGUAGE),
        "language": ("language", GAP),
        "gap": ("gap", FUNDS),
        "funds": ("funds", REFUSAL),
        "refusal": ("refusal", PHONE),
    }
    data_key, next_state = state_map[prefix]
    context.user_data[data_key] = answer

    if next_state == PHONE:
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("ارسال شماره تماس", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await query.edit_message_text(
            "برای نمایش نتیجه و امکان تماس مشاور، شماره خود را ارسال کنید.\n"
            "شماره فقط برای پیگیری همین درخواست استفاده می‌شود."
        )
        await query.message.reply_text(
            "روی دکمه زیر بزنید یا شماره را دستی وارد کنید:",
            reply_markup=keyboard,
        )
        return PHONE

    question, options = QUESTIONS[next_state]
    prefixes = {
        EDUCATION: "education",
        GPA: "gpa",
        LANGUAGE: "language",
        GAP: "gap",
        FUNDS: "funds",
        REFUSAL: "refusal",
    }
    await query.edit_message_text(
        question,
        reply_markup=keyboard_from_options(options, prefixes[next_state]),
    )
    return next_state


async def phone_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = (update.message.text or "").strip()

    cleaned = phone.replace(" ", "").replace("-", "")
    if len(cleaned) < 8:
        await update.message.reply_text("شماره معتبر نیست. دوباره ارسال کنید.")
        return PHONE

    context.user_data["phone"] = phone
    score = calculate_score(context.user_data)
    level, icon = score_level(score)
    save_result(update.effective_user, context.user_data, score, level)

    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{update.effective_user.id}"
    destination = DESTINATIONS[context.user_data["destination"]]

    result_text = (
        f"{icon} <b>نتیجه ارزیابی اولیه</b>\n\n"
        f"مقصد: <b>{destination}</b>\n"
        f"امتیاز اولیه: <b>{score} از ۱۰۰</b>\n"
        f"وضعیت: <b>{level}</b>\n\n"
        f"این امتیاز بر پایه پاسخ‌های شماست و تصمیم سفارت، پذیرش دانشگاه، "
        f"کیفیت مدارک و توضیح منطقی پرونده را جایگزین نمی‌کند.\n\n"
        f"برای تحلیل دقیق، پرونده باید توسط کارشناس بررسی شود."
    )
    share_text = (
        "من شانس اولیه پرونده تحصیلی‌ام را رایگان بررسی کردم. "
        "تو هم از این لینک امتحان کن:"
    )
    share_url = (
        "https://t.me/share/url?"
        f"url={referral_link}&text={share_text}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("درخواست بررسی تخصصی", url=CONSULTATION_URL)],
            [InlineKeyboardButton("ارسال تست برای یک دوست", url=share_url)],
            [InlineKeyboardButton("ارزیابی مجدد", callback_data="restart")],
        ]
    )
    await update.message.reply_text(
        result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    await update.message.reply_text(
        "ارزیابی تمام شد.",
        reply_markup=ReplyKeyboardRemove(),
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                (
                    "📥 لید جدید\n"
                    f"نام: {update.effective_user.full_name}\n"
                    f"یوزرنیم: @{update.effective_user.username or '-'}\n"
                    f"شماره: {phone}\n"
                    f"مقصد: {destination}\n"
                    f"امتیاز: {score}\n"
                    f"وضعیت: {level}"
                ),
            )
        except Exception:
            logging.exception("Could not notify admin %s", admin_id)

    return ConversationHandler.END


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    buttons = [
        InlineKeyboardButton(name, callback_data=f"destination|{key}")
        for key, name in DESTINATIONS.items()
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    await query.edit_message_text(
        "کشور مقصد موردنظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return DESTINATION


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "ارزیابی لغو شد. برای شروع دوباره /start را بزنید.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    with db_connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM leads WHERE phone IS NOT NULL").fetchone()["c"]
        today = datetime.now(timezone.utc).date().isoformat()
        today_count = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE phone IS NOT NULL AND substr(updated_at, 1, 10) = ?",
            (today,),
        ).fetchone()["c"]
        referrals = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE referred_by IS NOT NULL"
        ).fetchone()["c"]
    await update.message.reply_text(
        f"📊 آمار ربات\n\nکل لیدها: {total}\nلیدهای امروز: {today_count}\nورودی از معرفی: {referrals}"
    )


async def export_leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY updated_at DESC").fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(list(row))
    else:
        writer.writerow(["No leads"])

    file_bytes = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    file_bytes.name = "ava_visa_leads.csv"
    await update.message.reply_document(
        document=file_bytes,
        caption="خروجی لیدهای ربات",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Unhandled error", exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to the .env file.")

    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )
    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(False)
        .build()
    )

    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(begin, pattern=r"^begin$"),
            CallbackQueryHandler(restart, pattern=r"^restart$"),
        ],
        states={
            DESTINATION: [
                CallbackQueryHandler(begin, pattern=r"^begin$"),
                CallbackQueryHandler(destination_answer, pattern=r"^destination\|"),
            ],
            AGE: [CallbackQueryHandler(generic_answer, pattern=r"^age\|")],
            EDUCATION: [CallbackQueryHandler(generic_answer, pattern=r"^education\|")],
            GPA: [CallbackQueryHandler(generic_answer, pattern=r"^gpa\|")],
            LANGUAGE: [CallbackQueryHandler(generic_answer, pattern=r"^language\|")],
            GAP: [CallbackQueryHandler(generic_answer, pattern=r"^gap\|")],
            FUNDS: [CallbackQueryHandler(generic_answer, pattern=r"^funds\|")],
            REFUSAL: [CallbackQueryHandler(generic_answer, pattern=r"^refusal\|")],
            PHONE: [
                MessageHandler(filters.CONTACT, phone_answer),
                MessageHandler(filters.TEXT & ~filters.COMMAND, phone_answer),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        allow_reentry=True,
    )

    application.add_handler(conversation)
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("export", export_leads))
    application.add_error_handler(error_handler)

    print("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
