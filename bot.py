import csv
import io
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

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
    "CONSULTATION_URL", "https://avamohajerat.com/consult/"
).strip()
DB_PATH = os.getenv("DB_PATH", "data/leads.db").strip()
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/avamohajerat").strip()

AGE, EDUCATION, GPA, FIELD, LANGUAGE_TEST, LANGUAGE_LEVEL, GAP, WORK_EXPERIENCE, FUNDS, REFUSAL, PHONE = range(11)

STATES = [AGE, EDUCATION, GPA, FIELD, LANGUAGE_TEST, LANGUAGE_LEVEL, GAP, WORK_EXPERIENCE, FUNDS, REFUSAL]

QUESTIONS = {
    AGE: (
        "سن فعلی شما چند سال است؟",
        ["زیر ۲۴", "۲۴ تا ۲۹", "۳۰ تا ۳۴", "۳۵ تا ۳۹", "۴۰ سال به بالا"],
    ),
    EDUCATION: (
        "آخرین مدرک تحصیلی اخذشده شما چیست؟",
        ["دیپلم", "کاردانی", "کارشناسی", "کارشناسی ارشد", "دکتری"],
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
    FIELD: (
        "رشته یا حوزه تحصیلی آخرین مدرک شما چیست؟",
        [
            "مهندسی و فناوری",
            "کامپیوتر، IT و داده",
            "مدیریت، اقتصاد و مالی",
            "علوم پایه",
            "پزشکی و پیراپزشکی",
            "علوم انسانی و اجتماعی",
            "حقوق",
            "هنر، معماری و طراحی",
            "سایر",
        ],
    ),
    LANGUAGE_TEST: (
        "در حال حاضر چه مدرک یا آزمون زبانی دارید؟",
        [
            "IELTS Academic",
            "TOEFL iBT",
            "PTE Academic",
            "Duolingo English Test",
            "LanguageCert",
            "Oxford ELLT",
            "آلمانی — Goethe / TestDaF / telc",
            "فرانسوی — DELF / DALF / TCF",
            "ایتالیایی — CILS / CELI",
            "در حال آماده‌سازی برای آزمون",
            "هنوز مدرک زبان ندارم",
            "سایر",
        ],
    ),
    LANGUAGE_LEVEL: (
        "وضعیت فعلی نمره یا سطح زبان شما چگونه است؟",
        [
            "نمره یا سطح مناسب و قابل ارائه",
            "نمره دارم ولی احتمالاً نیاز به بهبود دارد",
            "در انتظار نتیجه آزمون",
            "در حال آماده‌سازی",
            "بدون نمره یا مدرک",
        ],
    ),
    GAP: (
        "از پایان آخرین مقطع تحصیلی شما چقدر گذشته است؟",
        ["کمتر از ۲ سال", "۲ تا ۴ سال", "۵ تا ۷ سال", "بیشتر از ۷ سال"],
    ),
    WORK_EXPERIENCE: (
        "سابقه کار مرتبط با رشته یا مسیر تحصیلی دارید؟",
        [
            "بیش از ۳ سال سابقه مرتبط",
            "۱ تا ۳ سال سابقه مرتبط",
            "کمتر از ۱ سال سابقه مرتبط",
            "سابقه کار غیرمرتبط",
            "سابقه کار ندارم",
        ],
    ),
    FUNDS: (
        "وضعیت تمکن مالی قابل‌اثبات شما چگونه است؟",
        ["کامل و قابل اثبات", "نسبتاً مناسب", "نیازمند تکمیل", "فعلاً آماده نیست"],
    ),
    REFUSAL: (
        "آیا سابقه ریجکتی ویزا دارید؟",
        ["خیر", "بله، یک بار", "بله، بیش از یک بار"],
    ),
}

STATE_KEYS = {
    AGE: "age",
    EDUCATION: "education",
    GPA: "gpa",
    FIELD: "field",
    LANGUAGE_TEST: "language_test",
    LANGUAGE_LEVEL: "language_level",
    GAP: "gap",
    WORK_EXPERIENCE: "work_experience",
    FUNDS: "funds",
    REFUSAL: "refusal",
}

PREFIXES = {
    AGE: "age",
    EDUCATION: "education",
    GPA: "gpa",
    FIELD: "field",
    LANGUAGE_TEST: "language_test",
    LANGUAGE_LEVEL: "language_level",
    GAP: "gap",
    WORK_EXPERIENCE: "work_experience",
    FUNDS: "funds",
    REFUSAL: "refusal",
}

PREFIX_TO_STATE = {v: k for k, v in PREFIXES.items()}

SCORES = {
    AGE: {
        "زیر ۲۴": 11,
        "۲۴ تا ۲۹": 12,
        "۳۰ تا ۳۴": 10,
        "۳۵ تا ۳۹": 7,
        "۴۰ سال به بالا": 4,
    },
    EDUCATION: {
        "دیپلم": 6,
        "کاردانی": 6,
        "کارشناسی": 10,
        "کارشناسی ارشد": 11,
        "دکتری": 10,
    },
    GPA: {
        "۱۸ تا ۲۰ — عالی": 12,
        "۱۶ تا ۱۷.۹۹ — خیلی خوب": 10,
        "۱۴ تا ۱۵.۹۹ — خوب": 8,
        "۱۲ تا ۱۳.۹۹ — متوسط": 5,
        "کمتر از ۱۲ — ضعیف": 2,
    },
    FIELD: {
        "مهندسی و فناوری": 8,
        "کامپیوتر، IT و داده": 9,
        "مدیریت، اقتصاد و مالی": 8,
        "علوم پایه": 8,
        "پزشکی و پیراپزشکی": 7,
        "علوم انسانی و اجتماعی": 6,
        "حقوق": 5,
        "هنر، معماری و طراحی": 6,
        "سایر": 5,
    },
    LANGUAGE_TEST: {
        "IELTS Academic": 8,
        "TOEFL iBT": 8,
        "PTE Academic": 8,
        "Duolingo English Test": 6,
        "LanguageCert": 6,
        "Oxford ELLT": 6,
        "آلمانی — Goethe / TestDaF / telc": 8,
        "فرانسوی — DELF / DALF / TCF": 8,
        "ایتالیایی — CILS / CELI": 8,
        "در حال آماده‌سازی برای آزمون": 4,
        "هنوز مدرک زبان ندارم": 1,
        "سایر": 4,
    },
    LANGUAGE_LEVEL: {
        "نمره یا سطح مناسب و قابل ارائه": 10,
        "نمره دارم ولی احتمالاً نیاز به بهبود دارد": 7,
        "در انتظار نتیجه آزمون": 6,
        "در حال آماده‌سازی": 4,
        "بدون نمره یا مدرک": 1,
    },
    GAP: {
        "کمتر از ۲ سال": 10,
        "۲ تا ۴ سال": 8,
        "۵ تا ۷ سال": 5,
        "بیشتر از ۷ سال": 2,
    },
    WORK_EXPERIENCE: {
        "بیش از ۳ سال سابقه مرتبط": 9,
        "۱ تا ۳ سال سابقه مرتبط": 7,
        "کمتر از ۱ سال سابقه مرتبط": 5,
        "سابقه کار غیرمرتبط": 3,
        "سابقه کار ندارم": 1,
    },
    FUNDS: {
        "کامل و قابل اثبات": 10,
        "نسبتاً مناسب": 7,
        "نیازمند تکمیل": 4,
        "فعلاً آماده نیست": 0,
    },
    REFUSAL: {
        "خیر": 8,
        "بله، یک بار": 4,
        "بله، بیش از یک بار": 1,
    },
}

COUNTRIES = [
    ("ایتالیا", "🇮🇹", 3),
    ("فرانسه", "🇫🇷", 2),
    ("انگلستان", "🇬🇧", 0),
    ("آلمان", "🇩🇪", -1),
    ("اتریش", "🇦🇹", -2),
    ("سوئد", "🇸🇪", -3),
]


def db_connect():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
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
                age TEXT,
                education TEXT,
                gpa TEXT,
                field TEXT,
                language_test TEXT,
                language_level TEXT,
                study_gap TEXT,
                work_experience TEXT,
                funds TEXT,
                refusal TEXT,
                overall_score INTEGER,
                best_country TEXT,
                best_country_score INTEGER,
                result_level TEXT,
                referred_by INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(leads)").fetchall()
        }

        required_columns = {
            "field": "TEXT",
            "language_test": "TEXT",
            "language_level": "TEXT",
            "work_experience": "TEXT",
        }

        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                conn.execute(
                    f"ALTER TABLE leads ADD COLUMN {column_name} {column_type}"
                )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                event_name TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()


def record_event(user_id, event_name):
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO events (telegram_id, event_name, created_at) VALUES (?, ?, ?)",
            (user_id, event_name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def upsert_user(user, referred_by=None):
    now = datetime.now(timezone.utc).isoformat()
    with db_connect() as conn:
        row = conn.execute(
            "SELECT telegram_id, referred_by FROM leads WHERE telegram_id = ?",
            (user.id,),
        ).fetchone()

        if row:
            if referred_by and not row["referred_by"] and referred_by != user.id:
                conn.execute(
                    "UPDATE leads SET referred_by = ?, updated_at = ? WHERE telegram_id = ?",
                    (referred_by, now, user.id),
                )
        else:
            conn.execute(
                """
                INSERT INTO leads (
                    telegram_id, username, full_name,
                    referred_by, created_at, updated_at
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
        conn.commit()


def save_result(user, data, score, best_country, best_score, level):
    now = datetime.now(timezone.utc).isoformat()
    with db_connect() as conn:
        conn.execute(
            """
            INSERT INTO leads (
                telegram_id, username, full_name, phone,
                age, education, gpa, field, language_test, language_level,
                study_gap, work_experience, funds, refusal, overall_score, best_country,
                best_country_score, result_level, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                phone=excluded.phone,
                age=excluded.age,
                education=excluded.education,
                gpa=excluded.gpa,
                field=excluded.field,
                language_test=excluded.language_test,
                language_level=excluded.language_level,
                study_gap=excluded.study_gap,
                work_experience=excluded.work_experience,
                funds=excluded.funds,
                refusal=excluded.refusal,
                overall_score=excluded.overall_score,
                best_country=excluded.best_country,
                best_country_score=excluded.best_country_score,
                result_level=excluded.result_level,
                updated_at=excluded.updated_at
            """,
            (
                user.id,
                user.username or "",
                user.full_name or "",
                data.get("phone", ""),
                data.get("age", ""),
                data.get("education", ""),
                data.get("gpa", ""),
                data.get("field", ""),
                data.get("language_test", ""),
                data.get("language_level", ""),
                data.get("gap", ""),
                data.get("work_experience", ""),
                data.get("funds", ""),
                data.get("refusal", ""),
                score,
                best_country,
                best_score,
                level,
                now,
                now,
            ),
        )
        conn.commit()


def progress(state):
    index = STATES.index(state) + 1
    total = len(STATES)
    percent = round((index - 1) / total * 100)
    blocks = round(percent / 10)
    bar = "█" * blocks + "░" * (10 - blocks)
    return f"مرحله {index} از {total}\n{bar} {percent}%\n\n"


def keyboard_for(state):
    _, options = QUESTIONS[state]
    prefix = PREFIXES[state]
    rows = [
        [InlineKeyboardButton(option, callback_data=f"answer|{prefix}|{i}")]
        for i, option in enumerate(options)
    ]

    if state != AGE:
        rows.append(
            [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"back|{prefix}")]
        )

    return InlineKeyboardMarkup(rows)


def question_message(state):
    return progress(state) + QUESTIONS[state][0]


def base_score(data):
    total = 0
    for state, key in STATE_KEYS.items():
        total += SCORES[state].get(data.get(key, ""), 0)
    return max(0, min(100, total))


def country_scores(data):
    score = base_score(data)
    results = [
        {"name": name, "flag": flag, "score": max(0, min(100, score + adjustment))}
        for name, flag, adjustment in COUNTRIES
    ]
    return sorted(results, key=lambda x: x["score"], reverse=True)


def score_level(score):
    if score >= 76:
        return "پرونده اولیه قوی", "🟢"
    if score >= 58:
        return "قابل اقدام، با نیاز به بهینه‌سازی", "🟡"
    if score >= 40:
        return "ریسک متوسط رو به بالا", "🟠"
    return "فعلاً پرریسک", "🔴"


def factor_text(data, strongest=True):
    labels = {
        AGE: "سن",
        EDUCATION: "مقطع تحصیلی",
        GPA: "معدل",
        FIELD: "رشته تحصیلی",
        LANGUAGE_TEST: "نوع مدرک زبان",
        LANGUAGE_LEVEL: "سطح یا نمره زبان",
        GAP: "فاصله تحصیلی",
        WORK_EXPERIENCE: "سابقه کار مرتبط",
        FUNDS: "تمکن مالی",
        REFUSAL: "سابقه ویزا",
    }
    ranked = []
    for state, key in STATE_KEYS.items():
        answer = data.get(key, "")
        ranked.append((SCORES[state].get(answer, 0), state, answer))

    ranked.sort(key=lambda x: x[0], reverse=strongest)
    _, state, answer = ranked[0]
    return f"{labels[state]}: {answer}"


def improvement_tip(data):
    if data.get("language_test") == "هنوز مدرک زبان ندارم":
        return "اولویت نخست شما، انتخاب آزمون زبان متناسب با کشور و دانشگاه هدف است."

    if data.get("language_level") in {
        "بدون نمره یا مدرک",
        "در حال آماده‌سازی",
        "نمره دارم ولی احتمالاً نیاز به بهبود دارد",
    }:
        return "تقویت نمره زبان می‌تواند گزینه‌های دانشگاهی و کیفیت پرونده را بهتر کند."

    if data.get("funds") in {"فعلاً آماده نیست", "نیازمند تکمیل"}:
        return "تمکن مالی باید قبل از اقدام، مستند و قابل دفاع شود."

    if data.get("gap") in {"۵ تا ۷ سال", "بیشتر از ۷ سال"}:
        return "برای فاصله تحصیلی باید توضیح منطقی و مستند آماده شود."

    if data.get("work_experience") in {
        "سابقه کار غیرمرتبط",
        "سابقه کار ندارم",
    }:
        return "ساختن ارتباط روشن بین رشته، سوابق و هدف تحصیلی برای شما اهمیت زیادی دارد."

    if data.get("refusal") != "خیر":
        return "پرونده ریجکتی قبلی باید قبل از اقدام جدید دقیق بررسی شود."

    return "مهم‌ترین فرصت شما، انتخاب درست کشور و دانشگاه متناسب با رشته و رزومه است."


async def show_question(query, state):
    await query.edit_message_text(
        question_message(state),
        reply_markup=keyboard_for(state),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = None

    if context.args and context.args[0].startswith("ref_"):
        raw = context.args[0].replace("ref_", "", 1)
        if raw.isdigit():
            referred_by = int(raw)

    upsert_user(user, referred_by)
    record_event(user.id, "start")
    context.user_data.clear()

    text = (
        f"سلام {user.first_name or ''} 👋\n\n"
        "🎓 <b>Visa DNA | ارزیابی اولیه پرونده تحصیلی</b>\n\n"
        "در کمتر از دو دقیقه، شرایط اولیه شما بررسی می‌شود و در پایان می‌بینید:\n\n"
        "• امتیاز کلی پرونده\n"
        "• مناسب‌ترین کشورهای پیشنهادی\n"
        "• مهم‌ترین نقطه قوت و ضعف\n"
        "• یک پیشنهاد عملی برای بهبود شرایط\n\n"
        "📢 برای دریافت نکات، اخبار و فرصت‌های تحصیلی، کانال رسمی آوا را هم دنبال کنید.\n\n"
        "⚠️ این نتیجه ارزیابی مقدماتی است و تضمین پذیرش یا صدور ویزا نیست."
    )

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("شروع ارزیابی رایگان", callback_data="begin")]]
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )
    return AGE


async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    record_event(update.effective_user.id, "begin")
    await show_question(query, AGE)
    return AGE


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, prefix, raw_index = query.data.split("|", 2)
        state = PREFIX_TO_STATE[prefix]
        index = int(raw_index)
        selected = QUESTIONS[state][1][index]
    except (ValueError, KeyError, IndexError, AttributeError):
        await query.edit_message_text(
            "انتخاب نامعتبر بود. لطفاً دوباره /start را بزنید."
        )
        return ConversationHandler.END

    context.user_data[STATE_KEYS[state]] = selected
    record_event(update.effective_user.id, f"answer_{prefix}")

    current = STATES.index(state)
    if current == len(STATES) - 1:
        phone_markup = ReplyKeyboardMarkup(
            [[KeyboardButton("ارسال شماره تماس", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

        await query.edit_message_text(
            "ارزیابی شما آماده است ✅\n\n"
            "برای نمایش نتیجه کامل و ثبت درخواست بررسی تخصصی، شماره تماس خود را ارسال کنید.\n\n"
            "شماره فقط برای پیگیری همین درخواست استفاده می‌شود."
        )
        await query.message.reply_text(
            "روی دکمه زیر بزنید یا شماره را دستی وارد کنید:",
            reply_markup=phone_markup,
        )
        return PHONE

    next_state = STATES[current + 1]
    await show_question(query, next_state)
    return next_state


async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        _, prefix = query.data.split("|", 1)
        state = PREFIX_TO_STATE[prefix]
        index = STATES.index(state)
    except (ValueError, KeyError):
        return ConversationHandler.END

    previous = STATES[max(0, index - 1)]
    await show_question(query, previous)
    return previous


async def phone_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = (update.message.text or "").strip()

    cleaned = (
        phone.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace("+", "")
    )

    if len(cleaned) < 8 or not cleaned.isdigit():
        await update.message.reply_text(
            "شماره واردشده معتبر نیست. دوباره ارسال کنید."
        )
        return PHONE

    context.user_data["phone"] = phone

    total_score = base_score(context.user_data)
    ranked_countries = country_scores(context.user_data)
    best = ranked_countries[0]
    level, icon = score_level(total_score)
    percentile = max(25, min(95, total_score + 8))

    save_result(
        update.effective_user,
        context.user_data,
        total_score,
        best["name"],
        best["score"],
        level,
    )
    record_event(update.effective_user.id, "completed")

    bot = await context.bot.get_me()
    referral_link = (
        f"https://t.me/{bot.username}?start=ref_{update.effective_user.id}"
    )

    top_three = "\n".join(
        f"{i + 1}. {item['flag']} <b>{item['name']}</b> — {item['score']}/100"
        for i, item in enumerate(ranked_countries[:3])
    )

    result_text = (
        f"{icon} <b>Visa DNA Report</b>\n\n"
        f"📊 امتیاز کلی: <b>{total_score}/100</b>\n"
        f"📌 وضعیت: <b>{level}</b>\n"
        f"🏅 بهتر از حدود <b>{percentile}٪</b> کاربران اولیه\n\n"
        f"<b>سه مقصد مناسب‌تر برای شرایط فعلی شما:</b>\n"
        f"{top_three}\n\n"
        f"✅ <b>نقطه قوت اصلی:</b>\n{factor_text(context.user_data, True)}\n\n"
        f"⚠️ <b>مهم‌ترین نقطه قابل بهبود:</b>\n"
        f"{factor_text(context.user_data, False)}\n\n"
        f"💡 <b>پیشنهاد عملی:</b>\n{improvement_tip(context.user_data)}\n\n"
        "🎁 <b>هدیه معرفی دوستان:</b>\n"
        "اگر ۳ نفر از طریق لینک اختصاصی شما وارد ربات شوند و ارزیابی را کامل کنند، "
        "یک جلسه مشاوره حضوری ۴۵ دقیقه‌ای همراه با تحلیل رایگان وضعیت مهاجرتی دریافت می‌کنید.\n\n"
        "📢 برای دریافت نکات کاربردی، فرصت‌ها و به‌روزرسانی‌های تحصیلی، "
        "کانال رسمی آوا را دنبال کنید.\n\n"
        "این گزارش یک غربالگری مقدماتی است و جایگزین بررسی تخصصی مدارک نیست."
    )

    share_text = (
        "🎯 من Visa DNA خودم را گرفتم و مناسب‌ترین مقصدهای تحصیلی‌ام مشخص شد.\n"
        "تو هم در کمتر از دو دقیقه تست رایگان را انجام بده 👇"
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={quote(referral_link, safe='')}"
        f"&text={quote(share_text, safe='')}"
    )

    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("درخواست بررسی تخصصی", url=CONSULTATION_URL)],
            [InlineKeyboardButton("عضویت در کانال رسمی آوا", url=CHANNEL_URL)],
            [InlineKeyboardButton("دعوت دوستان و دریافت هدیه", url=share_url)],
            [InlineKeyboardButton("پیگیری هدیه معرفی‌ها", callback_data="my_referrals")],
            [InlineKeyboardButton("ارزیابی مجدد", callback_data="restart")],
        ]
    )

    await update.message.reply_text(
        result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
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
                    "📥 لید جدید\n\n"
                    f"نام: {update.effective_user.full_name}\n"
                    f"یوزرنیم: @{update.effective_user.username or '-'}\n"
                    f"شماره: {phone}\n"
                    f"رشته: {context.user_data.get('field', '-')}\n"
                    f"مدرک زبان: {context.user_data.get('language_test', '-')}\n"
                    f"وضعیت زبان: {context.user_data.get('language_level', '-')}\n"
                    f"امتیاز کلی: {total_score}\n"
                    f"مقصد پیشنهادی اول: {best['name']}\n"
                    f"امتیاز مقصد اول: {best['score']}\n"
                    f"وضعیت: {level}"
                ),
            )
        except Exception:
            logging.exception("Could not notify admin %s", admin_id)

    return ConversationHandler.END


async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    with db_connect() as conn:
        invited = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE referred_by = ?",
            (user_id,),
        ).fetchone()["c"]

        completed = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM leads
            WHERE referred_by = ?
              AND phone IS NOT NULL
              AND phone != ''
            """,
            (user_id,),
        ).fetchone()["c"]

    bot_info = await context.bot.get_me()
    referral_link = (
        f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    )

    share_text = (
        "🎯 این تست رایگان، شرایط اولیه پرونده تحصیلی را "
        "در کمتر از دو دقیقه بررسی می‌کند. تو هم امتحان کن 👇"
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={quote(referral_link, safe='')}"
        f"&text={quote(share_text, safe='')}"
    )

    remaining = max(0, 3 - completed)

    if remaining == 0:
        reward_status = (
            "🎉 <b>شرط هدیه شما تکمیل شده است.</b>\n\n"
            "شما واجد دریافت یک جلسه مشاوره حضوری ۴۵ دقیقه‌ای "
            "همراه با تحلیل رایگان وضعیت مهاجرتی هستید. "
            "برای هماهنگی، روی دکمه «دریافت جلسه رایگان» بزنید."
        )
        consultation_button_text = "دریافت جلسه رایگان"
    else:
        reward_status = (
            "🎁 با تکمیل ارزیابی توسط <b>۳ نفر</b> از دوستانتان، "
            "یک جلسه مشاوره حضوری ۴۵ دقیقه‌ای همراه با تحلیل رایگان "
            "وضعیت مهاجرتی دریافت می‌کنید.\n\n"
            f"تا فعال‌شدن هدیه: <b>{remaining} معرفی موفق دیگر</b>"
        )
        consultation_button_text = "شرایط مشاوره تخصصی"

    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("ارسال تست برای یک دوست", url=share_url)],
            [InlineKeyboardButton("عضویت در کانال رسمی آوا", url=CHANNEL_URL)],
            [
                InlineKeyboardButton(
                    consultation_button_text,
                    url=CONSULTATION_URL,
                )
            ],
        ]
    )

    await query.message.reply_text(
        "👥 <b>آمار معرفی شما</b>\n\n"
        f"ورودی از لینک شما: <b>{invited}</b>\n"
        f"ارزیابی کامل‌شده: <b>{completed}</b>\n\n"
        f"{reward_status}\n\n"
        "📢 برای دریافت نکات و فرصت‌های جدید، کانال رسمی آوا را هم دنبال کنید.",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await show_question(query, AGE)
    return AGE


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

    today = datetime.now(timezone.utc).date().isoformat()

    with db_connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE phone IS NOT NULL AND phone != ''"
        ).fetchone()["c"]
        today_total = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM leads
            WHERE phone IS NOT NULL
              AND phone != ''
              AND substr(updated_at, 1, 10) = ?
            """,
            (today,),
        ).fetchone()["c"]
        starts = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE event_name = 'start'"
        ).fetchone()["c"]
        completed = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE event_name = 'completed'"
        ).fetchone()["c"]
        referred = conn.execute(
            "SELECT COUNT(*) AS c FROM leads WHERE referred_by IS NOT NULL"
        ).fetchone()["c"]

    rate = round(completed / starts * 100, 1) if starts else 0

    await update.message.reply_text(
        "📊 آمار ربات\n\n"
        f"کل لیدها: {total}\n"
        f"لیدهای امروز: {today_total}\n"
        f"شروع ارزیابی: {starts}\n"
        f"تکمیل ارزیابی: {completed}\n"
        f"نرخ تکمیل: {rate}%\n"
        f"ورودی از معرفی: {referred}"
    )


async def export_leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    with db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY updated_at DESC"
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(list(row))
    else:
        writer.writerow(["No leads"])

    file_data = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    file_data.name = "ava_visa_leads.csv"

    await update.message.reply_document(
        document=file_data,
        caption="خروجی لیدهای ربات",
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Unhandled error", exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing in Railway Variables.")

    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )

    init_db()

    app = (
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
            AGE: [
                CallbackQueryHandler(answer, pattern=r"^answer\|age\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            EDUCATION: [
                CallbackQueryHandler(answer, pattern=r"^answer\|education\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            GPA: [
                CallbackQueryHandler(answer, pattern=r"^answer\|gpa\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            FIELD: [
                CallbackQueryHandler(answer, pattern=r"^answer\|field\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            LANGUAGE_TEST: [
                CallbackQueryHandler(answer, pattern=r"^answer\|language_test\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            LANGUAGE_LEVEL: [
                CallbackQueryHandler(answer, pattern=r"^answer\|language_level\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            GAP: [
                CallbackQueryHandler(answer, pattern=r"^answer\|gap\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            WORK_EXPERIENCE: [
                CallbackQueryHandler(answer, pattern=r"^answer\|work_experience\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            FUNDS: [
                CallbackQueryHandler(answer, pattern=r"^answer\|funds\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            REFUSAL: [
                CallbackQueryHandler(answer, pattern=r"^answer\|refusal\|"),
                CallbackQueryHandler(back, pattern=r"^back\|"),
            ],
            PHONE: [
                MessageHandler(filters.CONTACT, phone_answer),
                MessageHandler(filters.TEXT & ~filters.COMMAND, phone_answer),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )

    app.add_handler(conversation)
    app.add_handler(
        CallbackQueryHandler(referrals, pattern=r"^my_referrals$")
    )
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("export", export_leads))
    app.add_error_handler(error_handler)

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
