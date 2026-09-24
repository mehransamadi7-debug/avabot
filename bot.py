import csv
import html
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


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

CONSULTATION_URL = os.getenv(
    "CONSULTATION_URL",
    "https://avamohajerat.com/consult/",
).strip()

CHANNEL_URL = os.getenv(
    "CHANNEL_URL",
    "https://t.me/avamohajerat",
).strip()

DB_PATH = os.getenv(
    "DB_PATH",
    "data/leads_v2.db",
).strip()


# ============================================================
# STATES
# ============================================================

(
    AGE,
    EDUCATION,
    GPA,
    FIELD,
    LANGUAGE_TEST,
    LANGUAGE_LEVEL,
    GAP,
    WORK_EXPERIENCE,
    FUNDS,
    REFUSAL,
    PHONE,
) = range(11)

QUESTION_STATES = [
    AGE,
    EDUCATION,
    GPA,
    FIELD,
    LANGUAGE_TEST,
    LANGUAGE_LEVEL,
    GAP,
    WORK_EXPERIENCE,
    FUNDS,
    REFUSAL,
]

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

STATE_PREFIXES = {
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

PREFIX_TO_STATE = {
    value: key
    for key, value in STATE_PREFIXES.items()
}


# ============================================================
# QUESTIONS
# ============================================================

QUESTIONS = {
    AGE: (
        "چند سال دارید؟",
        [
            "زیر ۲۲ سال",
            "۲۲ تا ۲۵ سال",
            "۲۶ تا ۳۰ سال",
            "۳۱ تا ۳۵ سال",
            "بیشتر از ۳۵ سال",
        ],
    ),

    EDUCATION: (
        "آخرین مدرک تحصیلی شما چیست؟",
        [
            "دیپلم",
            "کاردانی",
            "کارشناسی",
            "کارشناسی ارشد",
            "دکتری",
        ],
    ),

    GPA: (
        "معدل آخرین مقطع تحصیلی شما چقدر است؟",
        [
            "کمتر از ۱۴",
            "۱۴ تا ۱۵.۹۹",
            "۱۶ تا ۱۷.۴۹",
            "۱۷.۵ تا ۱۸.۴۹",
            "۱۸.۵ به بالا",
        ],
    ),

    FIELD: (
        "رشته تحصیلی شما چیست؟",
        [
            "مهندسی و فنی",
            "کامپیوتر و IT",
            "علوم پایه",
            "پزشکی و پیراپزشکی",
            "مدیریت و اقتصاد",
            "علوم انسانی",
            "هنر و معماری",
            "سایر رشته‌ها",
        ],
    ),

    LANGUAGE_TEST: (
        "وضعیت مدرک زبان شما چیست؟",
        [
            "IELTS",
            "TOEFL",
            "PTE",
            "مدرک زبان دیگری دارم",
            "هنوز مدرک زبان ندارم",
        ],
    ),

    LANGUAGE_LEVEL: (
        "سطح فعلی زبان شما را چطور ارزیابی می‌کنید؟",
        [
            "بدون نمره یا مدرک",
            "در حال آماده‌سازی",
            "نمره دارم ولی احتمالاً نیاز به بهبود دارد",
            "نمره مناسب دارم",
        ],
    ),

    GAP: (
        "فاصله تحصیلی شما چقدر است؟",
        [
            "بدون گپ یا کمتر از ۲ سال",
            "۲ تا ۴ سال",
            "۵ تا ۷ سال",
            "بیشتر از ۷ سال",
        ],
    ),

    WORK_EXPERIENCE: (
        "وضعیت سابقه کاری شما چیست؟",
        [
            "سابقه کار مرتبط دارم",
            "سابقه کار غیرمرتبط دارم",
            "سابقه کار ندارم",
        ],
    ),

    FUNDS: (
        "وضعیت تمکن مالی برای تحصیل و ویزا چگونه است؟",
        [
            "آماده و قابل اثبات",
            "نیازمند تکمیل",
            "فعلاً آماده نیست",
        ],
    ),

    REFUSAL: (
        "آیا سابقه ریجکتی ویزا داشته‌اید؟",
        [
            "خیر",
            "بله، یک بار",
            "بله، بیش از یک بار",
        ],
    ),
}


# ============================================================
# SCORING
# ============================================================

SCORES = {
    AGE: {
        "زیر ۲۲ سال": 12,
        "۲۲ تا ۲۵ سال": 10,
        "۲۶ تا ۳۰ سال": 8,
        "۳۱ تا ۳۵ سال": 5,
        "بیشتر از ۳۵ سال": 2,
    },

    EDUCATION: {
        "دیپلم": 5,
        "کاردانی": 6,
        "کارشناسی": 9,
        "کارشناسی ارشد": 10,
        "دکتری": 10,
    },

    GPA: {
        "کمتر از ۱۴": 2,
        "۱۴ تا ۱۵.۹۹": 5,
        "۱۶ تا ۱۷.۴۹": 8,
        "۱۷.۵ تا ۱۸.۴۹": 10,
        "۱۸.۵ به بالا": 12,
    },

    FIELD: {
        "مهندسی و فنی": 8,
        "کامپیوتر و IT": 10,
        "علوم پایه": 7,
        "پزشکی و پیراپزشکی": 8,
        "مدیریت و اقتصاد": 7,
        "علوم انسانی": 6,
        "هنر و معماری": 7,
        "سایر رشته‌ها": 5,
    },

    LANGUAGE_TEST: {
        "IELTS": 8,
        "TOEFL": 8,
        "PTE": 8,
        "مدرک زبان دیگری دارم": 6,
        "هنوز مدرک زبان ندارم": 2,
    },

    LANGUAGE_LEVEL: {
        "بدون نمره یا مدرک": 0,
        "در حال آماده‌سازی": 3,
        "نمره دارم ولی احتمالاً نیاز به بهبود دارد": 6,
        "نمره مناسب دارم": 10,
    },

    GAP: {
        "بدون گپ یا کمتر از ۲ سال": 8,
        "۲ تا ۴ سال": 6,
        "۵ تا ۷ سال": 3,
        "بیشتر از ۷ سال": 1,
    },

    WORK_EXPERIENCE: {
        "سابقه کار مرتبط دارم": 8,
        "سابقه کار غیرمرتبط دارم": 4,
        "سابقه کار ندارم": 2,
    },

    FUNDS: {
        "آماده و قابل اثبات": 10,
        "نیازمند تکمیل": 5,
        "فعلاً آماده نیست": 1,
    },

    REFUSAL: {
        "خیر": 8,
        "بله، یک بار": 4,
        "بله، بیش از یک بار": 1,
    },
}


MAX_SCORE = sum(
    max(values.values())
    for values in SCORES.values()
)


COUNTRIES = [
    {
        "name": "ایتالیا",
        "flag": "🇮🇹",
        "adjustment": 3,
    },
    {
        "name": "فرانسه",
        "flag": "🇫🇷",
        "adjustment": 2,
    },
    {
        "name": "انگلستان",
        "flag": "🇬🇧",
        "adjustment": 0,
    },
    {
        "name": "آلمان",
        "flag": "🇩🇪",
        "adjustment": -1,
    },
    {
        "name": "اتریش",
        "flag": "🇦🇹",
        "adjustment": -2,
    },
    {
        "name": "سوئد",
        "flag": "🇸🇪",
        "adjustment": -3,
    },
]


# ============================================================
# DATABASE
# ============================================================

def db_connect():
    db_file = Path(DB_PATH)

    db_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        str(db_file)
    )

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
            for row in connection.execute(
                "PRAGMA table_info(leads)"
            ).fetchall()
        }

        required_columns = {
            "field": "TEXT",
            "language_test": "TEXT",
            "language_level": "TEXT",
            "work_experience": "TEXT",
            "overall_score": "INTEGER",
            "best_country": "TEXT",
            "best_country_score": "INTEGER",
            "result_level": "TEXT",
        }

        for column_name, column_type in required_columns.items():

            if column_name not in existing_columns:

                connection.execute(
                    f"""
                    ALTER TABLE leads
                    ADD COLUMN {column_name}
                    {column_type}
                    """
                )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                event_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        connection.commit()


def record_event(
    telegram_id,
    event_name,
):

    with db_connect() as connection:

        connection.execute(
            """
            INSERT INTO events (
                telegram_id,
                event_name,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                telegram_id,
                event_name,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

        connection.commit()


def upsert_start_user(
    user,
    referred_by=None,
):

    now = datetime.now(
        timezone.utc
    ).isoformat()

    with db_connect() as connection:

        existing = connection.execute(
            """
            SELECT telegram_id, referred_by
            FROM leads
            WHERE telegram_id = ?
            """,
            (
                user.id,
            ),
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
                    SET
                        referred_by = ?,
                        updated_at = ?
                    WHERE telegram_id = ?
                    """,
                    (
                        referred_by,
                        now,
                        user.id,
                    ),
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
                    referred_by,
                    now,
                    now,
                ),
            )

        connection.commit()


def save_result(
    user,
    data,
    overall_score,
    best_country,
    best_country_score,
    result_level,
):

    now = datetime.now(
        timezone.utc
    ).isoformat()

    with db_connect() as connection:

        connection.execute(
            """
            INSERT INTO leads (
                telegram_id,
                username,
                full_name,
                phone,
                age,
                education,
                gpa,
                field,
                language_test,
                language_level,
                study_gap,
                work_experience,
                funds,
                refusal,
                overall_score,
                best_country,
                best_country_score,
                result_level,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )

            ON CONFLICT(telegram_id)
            DO UPDATE SET

                username = excluded.username,
                full_name = excluded.full_name,
                phone = excluded.phone,
                age = excluded.age,
                education = excluded.education,
                gpa = excluded.gpa,
                field = excluded.field,
                language_test = excluded.language_test,
                language_level = excluded.language_level,
                study_gap = excluded.study_gap,
                work_experience = excluded.work_experience,
                funds = excluded.funds,
                refusal = excluded.refusal,
                overall_score = excluded.overall_score,
                best_country = excluded.best_country,
                best_country_score = excluded.best_country_score,
                result_level = excluded.result_level,
                updated_at = excluded.updated_at
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
                overall_score,
                best_country,
                best_country_score,
                result_level,
                now,
                now,
            ),
        )

        connection.commit()


# ============================================================
# SCORING FUNCTIONS
# ============================================================

def calculate_base_score(data):

    raw_score = 0

    for state, data_key in STATE_KEYS.items():

        answer = data.get(
            data_key,
            "",
        )

        raw_score += SCORES[state].get(
            answer,
            0,
        )

    score = (
        raw_score
        / MAX_SCORE
        * 100
    )

    return round(
        max(
            0,
            min(
                100,
                score,
            ),
        )
    )


def calculate_country_scores(data):

    base_score = calculate_base_score(
        data
    )

    results = []

    for country in COUNTRIES:

        score = max(
            0,
            min(
                100,
                base_score
                + country["adjustment"],
            ),
        )

        results.append(
            {
                "name": country["name"],
                "flag": country["flag"],
                "score": score,
            }
        )

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return results


def score_level(score):

    if score >= 76:
        return (
            "پرونده اولیه قوی",
            "🟢",
        )

    if score >= 58:
        return (
            "قابل اقدام، با نیاز به بهینه‌سازی",
            "🟡",
        )

    if score >= 40:
        return (
            "ریسک متوسط رو به بالا",
            "🟠",
        )

    return (
        "فعلاً پرریسک",
        "🔴",
    )


def factor_text(
    data,
    strongest=True,
):

    labels = {
        AGE: "سن",
        EDUCATION: "تحصیلات",
        GPA: "معدل",
        FIELD: "رشته",
        LANGUAGE_TEST: "مدرک زبان",
        LANGUAGE_LEVEL: "سطح زبان",
        GAP: "گپ تحصیلی",
        WORK_EXPERIENCE: "سابقه کار",
        FUNDS: "تمکن مالی",
        REFUSAL: "سابقه ویزا",
    }

    ranked = []

    for state, data_key in STATE_KEYS.items():

        answer = data.get(
            data_key,
            "",
        )

        score = SCORES[state].get(
            answer,
            0,
        )

        ranked.append(
            (
                score,
                state,
                answer,
            )
        )

    ranked.sort(
        key=lambda x: x[0],
        reverse=strongest,
    )

    _, state, answer = ranked[0]

    return (
        f"{labels[state]}: "
        f"{answer}"
    )


def improvement_tip(data):

    if (
        data.get("language_test")
        == "هنوز مدرک زبان ندارم"
    ):
        return (
            "اولویت نخست شما، انتخاب آزمون زبان "
            "متناسب با کشور و دانشگاه هدف است."
        )

    if data.get(
        "language_level"
    ) in {
        "بدون نمره یا مدرک",
        "در حال آماده‌سازی",
        "نمره دارم ولی احتمالاً نیاز به بهبود دارد",
    }:
        return (
            "تقویت نمره زبان می‌تواند گزینه‌های "
            "دانشگاهی و کیفیت پرونده را بهتر کند."
        )

    if data.get("funds") in {
        "فعلاً آماده نیست",
        "نیازمند تکمیل",
    }:
        return (
            "تمکن مالی باید قبل از اقدام، "
            "مستند و قابل دفاع شود."
        )

    if data.get("gap") in {
        "۵ تا ۷ سال",
        "بیشتر از ۷ سال",
    }:
        return (
            "برای فاصله تحصیلی باید توضیح منطقی "
            "و مستند آماده شود."
        )

    if data.get(
        "work_experience"
    ) in {
        "سابقه کار غیرمرتبط دارم",
        "سابقه کار ندارم",
    }:
        return (
            "ساختن ارتباط روشن بین رشته، سوابق "
            "و هدف تحصیلی اهمیت زیادی دارد."
        )

    if data.get("refusal") != "خیر":
        return (
            "پرونده ریجکتی قبلی باید قبل از اقدام "
            "جدید دقیق بررسی شود."
        )

    return (
        "مهم‌ترین فرصت شما، انتخاب درست کشور "
        "و دانشگاه متناسب با رشته و رزومه است."
    )


# ============================================================
# UI
# ============================================================

def progress_text(state):

    current = (
        QUESTION_STATES.index(state)
        + 1
    )

    total = len(
        QUESTION_STATES
    )

    percent = round(
        (current - 1)
        / total
        * 100
    )

    blocks = round(
        percent / 10
    )

    bar = (
        "█" * blocks
        + "░" * (10 - blocks)
    )

    return (
        f"مرحله {current} از {total}\n"
        f"{bar} {percent}%\n\n"
    )


def question_keyboard(state):

    question, options = QUESTIONS[state]

    prefix = STATE_PREFIXES[state]

    rows = []

    for index, option in enumerate(
        options
    ):

        rows.append(
            [
                InlineKeyboardButton(
                    option,
                    callback_data=(
                        f"answer|{prefix}|{index}"
                    ),
                )
            ]
        )

    if state != AGE:

        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ بازگشت",
                    callback_data=(
                        f"back|{prefix}"
                    ),
                )
            ]
        )

    return InlineKeyboardMarkup(
        rows
    )


def question_message(state):

    question = QUESTIONS[state][0]

    return (
        progress_text(state)
        + question
    )


async def show_question(
    query,
    state,
):

    await query.edit_message_text(
        question_message(state),
        reply_markup=question_keyboard(
            state
        ),
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    referred_by = None

    if context.args:

        arg = context.args[0]

        if arg.startswith("ref_"):

            raw = arg.replace(
                "ref_",
                "",
                1,
            )

            if raw.isdigit():

                referred_by = int(raw)

    upsert_start_user(
        user,
        referred_by,
    )

    record_event(
        user.id,
        "start",
    )

    context.user_data.clear()

    first_name = html.escape(
        user.first_name or ""
    )

    text = (
        f"سلام {first_name} 👋\n\n"
        "🎓 <b>Visa DNA | ارزیابی اولیه پرونده تحصیلی</b>\n\n"
        "در کمتر از دو دقیقه، شرایط اولیه شما بررسی می‌شود "
        "و در پایان می‌بینید:\n\n"
        "• امتیاز کلی پرونده\n"
        "• سه مقصد پیشنهادی\n"
        "• اثر رشته و مدرک زبان بر شرایط شما\n"
        "• مهم‌ترین نقطه قوت و قابل‌بهبود\n"
        "• یک پیشنهاد عملی برای بهبود شرایط\n\n"
        "🎁 <b>هدیه معرفی دوستان</b>\n"
        "اگر ۳ نفر از طریق لینک اختصاصی شما وارد ربات شوند "
        "و ارزیابی را کامل کنند، یک جلسه مشاوره حضوری "
        "۴۵ دقیقه‌ای همراه با تحلیل رایگان وضعیت مهاجرتی "
        "دریافت می‌کنید.\n\n"
        "📢 برای دریافت نکات کاربردی و فرصت‌های تحصیلی، "
        "کانال رسمی آوا را هم دنبال کنید.\n\n"
        "⚠️ این ارزیابی مقدماتی است و تضمین پذیرش "
        "یا صدور ویزا نیست."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "شروع ارزیابی رایگان",
                    callback_data="begin",
                )
            ],
            [
                InlineKeyboardButton(
                    "عضویت در کانال رسمی آوا",
                    url=CHANNEL_URL,
                )
            ],
        ]
    )

    if update.message:

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    return AGE


async def begin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    record_event(
        update.effective_user.id,
        "begin",
    )

    await show_question(
        query,
        AGE,
    )

    return AGE


# ============================================================
# ANSWER
# ============================================================

async def answer_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    try:

        _, prefix, raw_index = (
            query.data.split(
                "|",
                2,
            )
        )

        state = PREFIX_TO_STATE[
            prefix
        ]

        index = int(
            raw_index
        )

        options = QUESTIONS[state][1]

        selected = options[index]

    except (
        ValueError,
        KeyError,
        IndexError,
        AttributeError,
    ):

        await query.edit_message_text(
            "انتخاب نامعتبر بود. "
            "لطفاً دوباره /start را بزنید."
        )

        return ConversationHandler.END

    data_key = STATE_KEYS[state]

    context.user_data[
        data_key
    ] = selected

    record_event(
        update.effective_user.id,
        f"answer_{prefix}",
    )

    current_index = (
        QUESTION_STATES.index(
            state
        )
    )

    if (
        current_index
        == len(QUESTION_STATES) - 1
    ):

        phone_keyboard = (
            ReplyKeyboardMarkup(
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
        )

        await query.edit_message_text(
            "ارزیابی شما آماده است ✅\n\n"
            "برای نمایش نتیجه کامل و ثبت درخواست "
            "بررسی تخصصی، شماره تماس خود را ارسال کنید.\n\n"
            "شماره فقط برای پیگیری همین درخواست استفاده می‌شود."
        )

        await query.message.reply_text(
            "روی دکمه زیر بزنید یا شماره را دستی وارد کنید:",
            reply_markup=phone_keyboard,
        )

        return PHONE

    next_state = QUESTION_STATES[
        current_index + 1
    ]

    await show_question(
        query,
        next_state,
    )

    return next_state


# ============================================================
# BACK
# ============================================================

async def back_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    try:

        _, prefix = query.data.split(
            "|",
            1,
        )

        current_state = (
            PREFIX_TO_STATE[prefix]
        )

        current_index = (
            QUESTION_STATES.index(
                current_state
            )
        )

    except (
        ValueError,
        KeyError,
    ):

        return ConversationHandler.END

    previous_state = QUESTION_STATES[
        max(
            0,
            current_index - 1,
        )
    ]

    await show_question(
        query,
        previous_state,
    )

    return previous_state


# ============================================================
# PHONE + RESULT
# ============================================================

async def phone_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return PHONE

    if update.message.contact:

        phone = (
            update.message.contact.phone_number
            or ""
        ).strip()

    else:

        phone = (
            update.message.text
            or ""
        ).strip()

    cleaned = (
        phone
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace("+", "")
    )

    if (
        len(cleaned) < 8
        or not cleaned.isdigit()
    ):

        await update.message.reply_text(
            "شماره واردشده معتبر نیست. دوباره ارسال کنید."
        )

        return PHONE

    context.user_data[
        "phone"
    ] = phone

    overall_score = (
        calculate_base_score(
            context.user_data
        )
    )

    country_results = (
        calculate_country_scores(
            context.user_data
        )
    )

    best_country = country_results[0]

    result_level, icon = (
        score_level(
            overall_score
        )
    )

    save_result(
        update.effective_user,
        context.user_data,
        overall_score,
        best_country["name"],
        best_country["score"],
        result_level,
    )

    record_event(
        update.effective_user.id,
        "completed",
    )

    bot_info = await context.bot.get_me()

    referral_link = (
        f"https://t.me/{bot_info.username}"
        f"?start=ref_"
        f"{update.effective_user.id}"
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

    top_three = "\n".join(
        (
            f"{index + 1}. "
            f"{item['flag']} "
            f"<b>{item['name']}</b> — "
            f"{item['score']}/100"
        )
        for index, item in enumerate(
            country_results[:3]
        )
    )

    result_text = (
        f"{icon} <b>Visa DNA Report</b>\n\n"
        f"📊 امتیاز کلی: <b>{overall_score}/100</b>\n"
        f"📌 وضعیت: <b>{result_level}</b>\n\n"

        "<b>سه مقصد مناسب‌تر برای شرایط فعلی شما:</b>\n"
        f"{top_three}\n\n"

        "✅ <b>نقطه قوت اصلی:</b>\n"
        f"{factor_text(context.user_data, True)}\n\n"

        "⚠️ <b>مهم‌ترین نقطه قابل بهبود:</b>\n"
        f"{factor_text(context.user_data, False)}\n\n"

        "💡 <b>پیشنهاد عملی:</b>\n"
        f"{improvement_tip(context.user_data)}\n\n"

        "🎁 <b>هدیه معرفی دوستان:</b>\n"
        "اگر ۳ نفر از طریق لینک اختصاصی شما وارد ربات شوند "
        "و ارزیابی را کامل کنند، یک جلسه مشاوره حضوری "
        "۴۵ دقیقه‌ای همراه با تحلیل رایگان وضعیت مهاجرتی "
        "دریافت می‌کنید.\n\n"

        "📢 برای دریافت نکات کاربردی و فرصت‌های تحصیلی، "
        "کانال رسمی آوا را دنبال کنید.\n\n"

        "این گزارش یک غربالگری مقدماتی است و جایگزین "
        "بررسی تخصصی مدارک نیست."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "درخواست مشاوره اختصاصی",
                    url=CONSULTATION_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "عضویت در کانال رسمی آوا",
                    url=CHANNEL_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "دعوت دوستان و دریافت هدیه",
                    url=share_url,
                )
            ],
            [
                InlineKeyboardButton(
                    "پیگیری هدیه معرفی‌ها",
                    callback_data="my_referrals",
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
        reply_markup=keyboard,
    )

    await update.message.reply_text(
        "ارزیابی تمام شد.",
        reply_markup=ReplyKeyboardRemove(),
    )

    # ارسال لید برای ادمین‌ها
    for admin_id in ADMIN_IDS:

        try:

            admin_text = (
                "📥 <b>لید جدید</b>\n\n"
                f"نام: "
                f"{html.escape(update.effective_user.full_name or '-')}\n"
                f"یوزرنیم: "
                f"@{html.escape(update.effective_user.username or '-')}\n"
                f"شماره: "
                f"{html.escape(phone)}\n"
                f"رشته: "
                f"{html.escape(context.user_data.get('field', '-'))}\n"
                f"مدرک زبان: "
                f"{html.escape(context.user_data.get('language_test', '-'))}\n"
                f"وضعیت زبان: "
                f"{html.escape(context.user_data.get('language_level', '-'))}\n"
                f"سابقه کار: "
                f"{html.escape(context.user_data.get('work_experience', '-'))}\n"
                f"امتیاز کلی: "
                f"{overall_score}\n"
                f"مقصد پیشنهادی اول: "
                f"{best_country['name']}\n"
                f"امتیاز مقصد اول: "
                f"{best_country['score']}\n"
                f"وضعیت: "
                f"{result_level}"
            )

            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                parse_mode=ParseMode.HTML,
            )

        except Exception:

            logging.exception(
                "Could not notify admin %s",
                admin_id,
            )

    return ConversationHandler.END


# ============================================================
# REFERRALS
# ============================================================

async def referrals_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = (
        update.effective_user.id
    )

    with db_connect() as connection:

        invited_count = (
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM leads
                WHERE referred_by = ?
                """,
                (
                    user_id,
                ),
            ).fetchone()["count"]
        )

        completed_count = (
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM leads
                WHERE referred_by = ?
                AND phone IS NOT NULL
                AND phone != ''
                """,
                (
                    user_id,
                ),
            ).fetchone()["count"]
        )

    bot_info = await context.bot.get_me()

    referral_link = (
        f"https://t.me/{bot_info.username}"
        f"?start=ref_{user_id}"
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

    remaining = max(
        0,
        3 - completed_count,
    )

    if remaining == 0:

        reward_status = (
            "🎉 <b>شرط دریافت هدیه تکمیل شده است.</b>\n\n"
            "شما واجد دریافت یک جلسه مشاوره حضوری "
            "۴۵ دقیقه‌ای همراه با تحلیل رایگان وضعیت مهاجرتی هستید.\n\n"
            "برای ثبت درخواست، روی دکمه زیر بزنید."
        )

        consultation_text = (
            "ثبت جلسه رایگان"
        )

    else:

        reward_status = (
            "🎁 با تکمیل ارزیابی توسط <b>۳ نفر</b> "
            "از دوستانتان، یک جلسه مشاوره حضوری "
            "۴۵ دقیقه‌ای همراه با تحلیل رایگان وضعیت مهاجرتی "
            "دریافت می‌کنید.\n\n"
            f"تا فعال‌شدن هدیه: "
            f"<b>{remaining} معرفی موفق دیگر</b>"
        )

        consultation_text = (
            "درخواست مشاوره اختصاصی"
        )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "ارسال تست برای یک دوست",
                    url=share_url,
                )
            ],
            [
                InlineKeyboardButton(
                    "عضویت در کانال رسمی آوا",
                    url=CHANNEL_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    consultation_text,
                    url=CONSULTATION_URL,
                )
            ],
        ]
    )

    await query.message.reply_text(
        "👥 <b>آمار معرفی شما</b>\n\n"
        f"ورودی از لینک شما: "
        f"<b>{invited_count}</b>\n"
        f"ارزیابی کامل‌شده: "
        f"<b>{completed_count}</b>\n\n"
        f"{reward_status}",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ============================================================
# RESTART
# ============================================================

async def restart(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    context.user_data.clear()

    await show_question(
        query,
        AGE,
    )

    return AGE


# ============================================================
# CANCEL
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.clear()

    if update.message:

        await update.message.reply_text(
            "ارزیابی لغو شد. "
            "برای شروع دوباره /start را بزنید.",
            reply_markup=ReplyKeyboardRemove(),
        )

    return ConversationHandler.END


# ============================================================
# ADMIN STATS
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if (
        not update.effective_user
        or update.effective_user.id
        not in ADMIN_IDS
    ):
        return

    today = (
        datetime.now(
            timezone.utc
        ).date().isoformat()
    )

    with db_connect() as connection:

        total_leads = (
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM leads
                WHERE phone IS NOT NULL
                AND phone != ''
                """
            ).fetchone()["count"]
        )

        today_leads = (
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM leads
                WHERE phone IS NOT NULL
                AND phone != ''
                AND substr(updated_at, 1, 10) = ?
                """,
                (
                    today,
                ),
            ).fetchone()["count"]
        )

        starts = (
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM events
                WHERE event_name = 'start'
                """
            ).fetchone()["count"]
        )

        completed = (
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM events
                WHERE event_name = 'completed'
                """
            ).fetchone()["count"]
        )

        referred = (
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM leads
                WHERE referred_by IS NOT NULL
                """
            ).fetchone()["count"]
        )

    completion_rate = (
        round(
            completed / starts * 100,
            1,
        )
        if starts
        else 0
    )

    await update.message.reply_text(
        "📊 <b>آمار ربات</b>\n\n"
        f"کل لیدها: {total_leads}\n"
        f"لیدهای امروز: {today_leads}\n"
        f"شروع ارزیابی: {starts}\n"
        f"تکمیل ارزیابی: {completed}\n"
        f"نرخ تکمیل: {completion_rate}%\n"
        f"ورودی از معرفی: {referred}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# EXPORT
# ============================================================

async def export_leads(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if (
        not update.effective_user
        or update.effective_user.id
        not in ADMIN_IDS
    ):
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

    writer = csv.writer(
        output
    )

    if rows:

        writer.writerow(
            rows[0].keys()
        )

        for row in rows:

            writer.writerow(
                list(row)
            )

    else:

        writer.writerow(
            ["No leads"]
        )

    file_bytes = io.BytesIO(
        output.getvalue().encode(
            "utf-8-sig"
        )
    )

    file_bytes.name = (
        "ava_visa_leads.csv"
    )

    await update.message.reply_document(
        document=file_bytes,
        caption="خروجی لیدهای ربات",
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):

    logging.exception(
        "Unhandled error",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is missing in Railway Variables."
        )

    logging.basicConfig(
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
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
            CommandHandler(
                "start",
                start,
            ),

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

            AGE: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            EDUCATION: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            GPA: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            FIELD: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            LANGUAGE_TEST: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            LANGUAGE_LEVEL: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            GAP: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            WORK_EXPERIENCE: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            FUNDS: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            REFUSAL: [
                CallbackQueryHandler(
                    answer_question,
                    pattern=r"^answer\|",
                ),
                CallbackQueryHandler(
                    back_question,
                    pattern=r"^back\|",
                ),
            ],

            PHONE: [
                MessageHandler(
                    filters.CONTACT,
                    phone_answer,
                ),
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    phone_answer,
                ),
            ],
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel,
            ),
            CommandHandler(
                "start",
                start,
            ),
        ],

        allow_reentry=True,
    )

    application.add_handler(
        conversation
    )

    application.add_handler(
        CallbackQueryHandler(
            referrals_status,
            pattern=r"^my_referrals$",
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats,
        )
    )

    application.add_handler(
        CommandHandler(
            "export",
            export_leads,
        )
    )

    application.add_error_handler(
        error_handler
    )

    print(
        "Bot is running..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
