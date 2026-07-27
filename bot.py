import csv
import io
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

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
    int(item.strip())
    for item in os.getenv("ADMIN_IDS", "").split(",")
    if item.strip().isdigit()
}

CONSULTATION_URL = os.getenv(
    "CONSULTATION_URL",
    "https://t.me/visadesk_consult",
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
    "dont_know": "هنوز نمی‌دانم",
}


QUESTIONS = {
    AGE: (
        "سن فعلی شما چند سال است؟",
        [
            "زیر ۲۴",
            "۲۴ تا ۲۹",
            "۳۰ تا ۳۴",
            "۳۵ تا ۳۹",
            "۴۰ سال به بالا",
        ],
    ),
    EDUCATION: (
        "آخرین مدرک تحصیلی اخذشده شما چیست؟",
        [
            "دیپلم",
            "کاردانی",
            "کارشناسی",
            "کارشناسی ارشد",
            "دکتری",
        ],
    ),
    GPA: (
        "معدل آخرین مقطع تحصیلی شما چند بوده است؟",
        [
            "۱۸ تا ۲۰ — عالی",
            "۱۶ تا ۱۷.۹۹ — خیلی خوب",
            "۱۴ تا ۱۵.۹۹ — خوب",
            "۱۲ تا ۱۳.۹۹ — متوسط",
            "کمتر از ۱۲ — ضعیف",
        ],
    ),
    LANGUAGE: (
        "در حال حاضر چه مدرک یا سطح زبانی دارید؟",
        [
            "مدرک معتبر با سطح B2 یا بالاتر",
            "مدرک معتبر در سطح B1",
            "در حال آماده‌سازی برای آزمون",
            "بدون مدرک زبان",
        ],
    ),
    GAP: (
        "از پایان آخرین مقطع تحصیلی شما چقدر گذشته است؟",
        [
            "کمتر از ۲ سال",
            "۲ تا ۴ سال",
            "۵ تا ۷ سال",
            "بیشتر از ۷ سال",
        ],
    ),
    FUNDS: (
        "وضعیت تمکن مالی قابل‌اثبات شما چگونه است؟",
        [
            "کامل و قابل اثبات",
            "نسبتاً مناسب",
            "نیازمند تکمیل",
            "فعلاً آماده نیست",
        ],
    ),
    REFUSAL: (
        "آیا سابقه ریجکتی ویزا دارید؟",
        [
            "خیر",
            "بله، یک بار",
            "بله، بیش از یک بار",
        ],
    ),
}


SCORES = {
    AGE: {
        "زیر ۲۴": 14,
        "۲۴ تا ۲۹": 15,
        "۳۰ تا ۳۴": 12,
        "۳۵ تا ۳۹": 8,
        "۴۰ سال به بالا": 4,
    },
    EDUCATION: {
        "دیپلم": 8,
        "کاردانی": 7,
        "کارشناسی": 12,
        "کارشناسی ارشد": 13,
        "دکتری": 11,
    },
    GPA: {
        "۱۸ تا ۲۰ — عالی": 15,
        "۱۶ تا ۱۷.۹۹ — خیلی خوب": 13,
        "۱۴ تا ۱۵.۹۹ — خوب": 10,
        "۱۲ تا ۱۳.۹۹ — متوسط": 6,
        "کمتر از ۱۲ — ضعیف": 2,
    },
    LANGUAGE: {
        "مدرک معتبر با سطح B2 یا بالاتر": 18,
        "مدرک معتبر در سطح B1": 13,
        "در حال آماده‌سازی برای آزمون": 7,
        "بدون مدرک زبان": 1,
    },
    GAP: {
        "کمتر از ۲ سال": 14,
        "۲ تا ۴ سال": 11,
        "۵ تا ۷ سال": 7,
        "بیشتر از ۷ سال": 2,
    },
    FUNDS: {
        "کامل و قابل اثبات": 17,
        "نسبتاً مناسب": 12,
        "نیازمند تکمیل": 6,
        "فعلاً آماده نیست": 0,
    },
    REFUSAL: {
        "خیر": 7,
        "بله، یک بار": 3,
        "بله، بیش از یک بار": 0,
    },
}


DESTINATION_ADJUSTMENT = {
    "uk": 0,
    "germany": -1,
    "italy": 2,
    "france": 1,
    "austria": -1,
    "sweden": -2,
    "dont_know": 0,
}


STATE_TO_DATA_KEY = {
    AGE: "age",
    EDUCATION: "education",
    GPA: "gpa",
    LANGUAGE: "language",
    GAP: "gap",
    FUNDS: "funds",
    REFUSAL: "refusal",
}


PREFIX_TO_STATE = {
    "age": AGE,
    "education": EDUCATION,
    "gpa": GPA,
    "language": LANGUAGE,
    "gap": GAP,
    "funds": FUNDS,
    "refusal": REFUSAL,
}


STATE_TO_PREFIX = {
    AGE: "age",
    EDUCATION: "education",
    GPA: "gpa",
    LANGUAGE: "language",
    GAP: "gap",
    FUNDS: "funds",
    REFUSAL: "refusal",
}


NEXT_STATE = {
    AGE: EDUCATION,
    EDUCATION: GPA,
    GPA: LANGUAGE,
    LANGUAGE: GAP,
    GAP: FUNDS,
    FUNDS: REFUSAL,
    REFUSAL: PHONE,
}


def db_connect():
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db_connect() as connection:
        connection.execute(
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
        connection.commit()


def upsert_start_user(user, referred_by=None):
    now = datetime.now(timezone.utc).isoformat()

    with db_connect() as connection:
        existing = connection.execute(
            """
            SELECT telegram_id, referred_by
            FROM leads
            WHERE telegram_id = ?
            """,
            (user.id,),
        ).fetchone()

        if existing:
            if (
                referred_by
                and not existing["referred_by"]
                and referred_by != user.id
            ):
                connection.execute(
                    """
                    UPDATE leads
                    SET referred_by = ?, updated_at = ?
                    WHERE telegram_id = ?
                    """,
                    (referred_by, now, user.id),
                )
        else:
            connection.execute(
                """
                INSERT INTO leads (
                    telegram_id,
                    username,
                    full_name,
                    referred_by,
                    created_at,
                    updated_at
                )
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

        connection.commit()


def save_result(user, data, score, level):
    now = datetime.now(timezone.utc).isoformat()

    destination_key = data.get("destination", "")
    destination_name = DESTINATIONS.get(
        destination_key,
        destination_key,
    )

    with db_connect() as connection:
        connection.execute(
            """
            INSERT INTO leads (
                telegram_id,
                username,
                full_name,
                phone,
                destination,
                age,
                education,
                gpa,
                language,
                study_gap,
                funds,
                refusal,
                score,
                result_level,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                phone = excluded.phone,
                destination = excluded.destination,
                age = excluded.age,
                education = excluded.education,
                gpa = excluded.gpa,
                language = excluded.language,
                study_gap = excluded.study_gap,
                funds = excluded.funds,
                refusal = excluded.refusal,
                score = excluded.score,
                result_level = excluded.result_level,
                updated_at = excluded.updated_at
            """,
            (
                user.id,
                user.username or "",
                user.full_name or "",
                data.get("phone", ""),
                destination_name,
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
        connection.commit()


def keyboard_from_options(options, prefix):
    rows = []

    for index, option in enumerate(options):
        rows.append(
            [
                InlineKeyboardButton(
                    option,
                    callback_data=f"{prefix}|{index}",
                )
            ]
        )

    return InlineKeyboardMarkup(rows)


def destination_keyboard():
    buttons = [
        InlineKeyboardButton(
            name,
            callback_data=f"destination|{key}",
        )
        for key, name in DESTINATIONS.items()
    ]

    rows = [
        buttons[index : index + 2]
        for index in range(0, len(buttons), 2)
    ]

    return InlineKeyboardMarkup(rows)


def calculate_score(data):
    score = 0

    for state, data_key in STATE_TO_DATA_KEY.items():
        answer = data.get(data_key, "")
        score += SCORES[state].get(answer, 0)

    destination_key = data.get("destination", "")
    score += DESTINATION_ADJUSTMENT.get(destination_key, 0)

    return max(0, min(100, score))


def score_level(score):
    if score >= 76:
        return "پرونده اولیه قوی", "🟢"

    if score >= 58:
        return "قابل اقدام، با نیاز به بهینه‌سازی", "🟡"

    if score >= 40:
        return "ریسک متوسط رو به بالا", "🟠"

    return "فعلاً پرریسک", "🔴"


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    referred_by = None

    if context.args and context.args[0].startswith("ref_"):
        raw_referrer = context.args[0].replace("ref_", "", 1)

        if raw_referrer.isdigit():
            referred_by = int(raw_referrer)

    upsert_start_user(user, referred_by)
    context.user_data.clear()

    text = (
        f"سلام {user.first_name or ''} 👋\n\n"
        "🎓 <b>ارزیابی اولیه پرونده تحصیلی</b>\n\n"
        "با پاسخ به چند سؤال کوتاه، نقاط قوت و ضعف اولیه "
        "پرونده شما بررسی می‌شود.\n\n"
        "⏱ زمان تقریبی: کمتر از ۲ دقیقه\n\n"
        "⚠️ این نتیجه یک ارزیابی مقدماتی است و به‌معنای "
        "تضمین پذیرش یا صدور ویزا نیست.\n\n"
        "برای شروع روی دکمه زیر بزنید."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "شروع ارزیابی رایگان",
                    callback_data="begin",
                )
            ]
        ]
    )

    if update.message:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    return DESTINATION


async def begin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "کشور مقصد موردنظر خود را انتخاب کنید:",
        reply_markup=destination_keyboard(),
    )

    return DESTINATION


async def destination_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    _, destination_key = query.data.split("|", 1)

    if destination_key not in DESTINATIONS:
        await query.edit_message_text(
            "گزینه انتخاب‌شده معتبر نیست. دوباره /start را بزنید."
        )
        return ConversationHandler.END

    context.user_data["destination"] = destination_key

    question, options = QUESTIONS[AGE]

    await query.edit_message_text(
        question,
        reply_markup=keyboard_from_options(options, "age"),
    )

    return AGE


async def generic_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    try:
        prefix, raw_index = query.data.split("|", 1)
        option_index = int(raw_index)
        current_state = PREFIX_TO_STATE[prefix]
        question, options = QUESTIONS[current_state]
        selected_answer = options[option_index]

    except (
        ValueError,
        KeyError,
        IndexError,
        AttributeError,
    ):
        await query.edit_message_text(
            "انتخاب نامعتبر بود. لطفاً دوباره /start را بزنید."
        )
        return ConversationHandler.END

    data_key = STATE_TO_DATA_KEY[current_state]
    context.user_data[data_key] = selected_answer

    next_state = NEXT_STATE[current_state]

    if next_state == PHONE:
        phone_keyboard = ReplyKeyboardMarkup(
            [
                [
                    KeyboardButton(
                        "ارسال شماره تماس",
                        request_contact=True,
                    )
                ]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

        await query.edit_message_text(
            "برای نمایش نتیجه و امکان تماس مشاور، "
            "شماره خود را ارسال کنید.\n\n"
            "شماره فقط برای پیگیری همین درخواست استفاده می‌شود."
        )

        await query.message.reply_text(
            "روی دکمه زیر بزنید یا شماره را دستی وارد کنید:",
            reply_markup=phone_keyboard,
        )

        return PHONE

    next_question, next_options = QUESTIONS[next_state]
    next_prefix = STATE_TO_PREFIX[next_state]

    await query.edit_message_text(
        next_question,
        reply_markup=keyboard_from_options(
            next_options,
            next_prefix,
        ),
    )

    return next_state


async def phone_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = (update.message.text or "").strip()

    cleaned_phone = (
        phone.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if len(cleaned_phone) < 8:
        await update.message.reply_text(
            "شماره واردشده معتبر نیست. دوباره ارسال کنید."
        )
        return PHONE

    context.user_data["phone"] = phone

    score = calculate_score(context.user_data)
    level, icon = score_level(score)

    save_result(
        update.effective_user,
        context.user_data,
        score,
        level,
    )

    bot_info = await context.bot.get_me()
    bot_username = bot_info.username

    referral_link = (
        f"https://t.me/{bot_username}"
        f"?start=ref_{update.effective_user.id}"
    )

    destination_key = context.user_data.get("destination", "")
    destination_name = DESTINATIONS.get(
        destination_key,
        destination_key,
    )

    result_text = (
        f"{icon} <b>نتیجه ارزیابی اولیه</b>\n\n"
        f"🌍 مقصد انتخابی: <b>{destination_name}</b>\n"
        f"📊 امتیاز اولیه: <b>{score} از ۱۰۰</b>\n"
        f"📌 وضعیت: <b>{level}</b>\n\n"
        "این امتیاز بر اساس پاسخ‌های ثبت‌شده محاسبه شده است "
        "و جایگزین بررسی مدارک، شرایط دانشگاه یا تصمیم سفارت نیست.\n\n"
        "برای تحلیل دقیق‌تر، پرونده باید توسط کارشناس بررسی شود."
    )

    share_text = (
        "🎯 من ارزیابی اولیه پرونده تحصیلی‌ام را انجام دادم.\n"
        "تو هم در کمتر از دو دقیقه نتیجه‌ات را ببین 👇"
    )

    share_url = "https://t.me/share/url?" + urlencode(
        {
            "url": referral_link,
            "text": share_text,
        }
    )

    result_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "درخواست بررسی تخصصی",
                    url=CONSULTATION_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "ارسال تست برای یک دوست",
                    url=share_url,
                )
            ],
            [
                InlineKeyboardButton(
                    "ارزیابی مجدد",
                    callback_data="restart",
                )
            ],
        ]
    )

    await update.message.reply_text(
        result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=result_keyboard,
    )

    await update.message.reply_text(
        "ارزیابی تمام شد.",
        reply_markup=ReplyKeyboardRemove(),
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "📥 لید جدید\n\n"
                    f"نام: {update.effective_user.full_name}\n"
                    f"یوزرنیم: @{update.effective_user.username or '-'}\n"
                    f"شماره: {phone}\n"
                    f"مقصد: {destination_name}\n"
                    f"امتیاز: {score}\n"
                    f"وضعیت: {level}"
                ),
            )
        except Exception:
            logging.exception(
                "Could not notify admin %s",
                admin_id,
            )

    return ConversationHandler.END


async def restart(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "کشور مقصد موردنظر خود را انتخاب کنید:",
        reply_markup=destination_keyboard(),
    )

    return DESTINATION


async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "ارزیابی لغو شد. برای شروع دوباره /start را بزنید.",
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id not in ADMIN_IDS:
        return

    with db_connect() as connection:
        total = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM leads
            WHERE phone IS NOT NULL
              AND phone != ''
            """
        ).fetchone()["count"]

        today = datetime.now(timezone.utc).date().isoformat()

        today_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM leads
            WHERE phone IS NOT NULL
              AND phone != ''
              AND substr(updated_at, 1, 10) = ?
            """,
            (today,),
        ).fetchone()["count"]

        referrals = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM leads
            WHERE referred_by IS NOT NULL
            """
        ).fetchone()["count"]

    await update.message.reply_text(
        "📊 آمار ربات\n\n"
        f"کل لیدها: {total}\n"
        f"لیدهای امروز: {today_count}\n"
        f"ورودی از معرفی: {referrals}"
    )


async def export_leads(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_user.id not in ADMIN_IDS:
        return

    with db_connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM leads
            ORDER BY updated_at DESC
            """
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    if rows:
        writer.writerow(rows[0].keys())

        for row in rows:
            writer.writerow(list(row))
    else:
        writer.writerow(["No leads"])

    file_bytes = io.BytesIO(
        output.getvalue().encode("utf-8-sig")
    )
    file_bytes.name = "ava_visa_leads.csv"

    await update.message.reply_document(
        document=file_bytes,
        caption="خروجی لیدهای ربات",
    )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logging.exception(
        "Unhandled error",
        exc_info=context.error,
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing. Add it to Railway Variables."
        )

    logging.basicConfig(
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
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
            CallbackQueryHandler(
                begin,
                pattern=r"^begin$",
            ),
            CallbackQueryHandler(
                restart,
                pattern=r"^restart$",
            ),
        ],
        states={
            DESTINATION: [
                CallbackQueryHandler(
                    begin,
                    pattern=r"^begin$",
                ),
                CallbackQueryHandler(
                    destination_answer,
                    pattern=r"^destination\|",
                ),
            ],
            AGE: [
                CallbackQueryHandler(
                    generic_answer,
                    pattern=r"^age\|",
                )
            ],
            EDUCATION: [
                CallbackQueryHandler(
                    generic_answer,
                    pattern=r"^education\|",
                )
            ],
            GPA: [
                CallbackQueryHandler(
                    generic_answer,
                    pattern=r"^gpa\|",
                )
            ],
            LANGUAGE: [
                CallbackQueryHandler(
                    generic_answer,
                    pattern=r"^language\|",
                )
            ],
            GAP: [
                CallbackQueryHandler(
                    generic_answer,
                    pattern=r"^gap\|",
                )
            ],
            FUNDS: [
                CallbackQueryHandler(
                    generic_answer,
                    pattern=r"^funds\|",
                )
            ],
            REFUSAL: [
                CallbackQueryHandler(
                    generic_answer,
                    pattern=r"^refusal\|",
                )
            ],
            PHONE: [
                MessageHandler(
                    filters.CONTACT,
                    phone_answer,
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    phone_answer,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )

    application.add_handler(conversation)
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("export", export_leads))
    application.add_error_handler(error_handler)

    print("Bot is running...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
