"""
bot.py - Tech Spotter Telegram Bot.
Digital Body Double & Consistency Engine for Namaste DSA & side project consistency.
"""

import asyncio
import functools
import logging
import os
from datetime import datetime, time, timedelta
from typing import Dict, Any, Optional

import pytz
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import database

# Load environment configuration
load_dotenv()

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("TechSpotterBot")

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID_RAW = os.getenv("TELEGRAM_USER_ID")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Kolkata")
DB_PATH = os.getenv("DB_PATH", database.DEFAULT_DB_PATH)

try:
    AUTHORIZED_USER_ID: Optional[int] = (
        int(TELEGRAM_USER_ID_RAW) if TELEGRAM_USER_ID_RAW else None
    )
except ValueError:
    AUTHORIZED_USER_ID = None

try:
    TIMEZONE = pytz.timezone(TIMEZONE_NAME)
except Exception:
    TIMEZONE = pytz.timezone("Asia/Kolkata")

# In-memory dictionary tracking active focus timers per user
# user_id -> {"job": Job, "block_number": int, "duration_mins": int, "start_time": datetime, "end_time": datetime, "session_type": str, "session_date": str, "topic": str}
active_timers: Dict[int, Dict[str, Any]] = {}


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Returns quick action buttons for one-tap mobile control."""
    keyboard = [
        [
            InlineKeyboardButton("⏱️ 15m", callback_data="block_15"),
            InlineKeyboardButton("⏱️ 30m", callback_data="block_30"),
            InlineKeyboardButton("⏱️ 45m", callback_data="block_45"),
            InlineKeyboardButton("⏱️ 60m", callback_data="block_60"),
        ],
        [
            InlineKeyboardButton("🛡️ Block 2 (Code)", callback_data="block_b2"),
            InlineKeyboardButton("🛑 Stop", callback_data="action_stop"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="action_status"),
            InlineKeyboardButton("📅 History", callback_data="action_history"),
            InlineKeyboardButton("📈 Weekly", callback_data="action_weekly"),
        ],
        [
            InlineKeyboardButton("🧊 Rest Day / Freeze", callback_data="action_freeze"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def reply(update: Update, text: str, **kwargs):
    """Safely replies to either a Message or a CallbackQuery."""
    if update.message:
        return await update.message.reply_text(text, **kwargs)
    elif update.callback_query and update.callback_query.message:
        return await update.callback_query.message.reply_text(text, **kwargs)


def restricted(func):
    """
    Security gatekeeper: silently ignores any incoming message
    that does not originate from the configured TELEGRAM_USER_ID.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or AUTHORIZED_USER_ID is None or user.id != AUTHORIZED_USER_ID:
            logger.warning(
                "Unauthorized access attempt from user: %s (id: %s)",
                user.username if user else "Unknown",
                user.id if user else "None",
            )
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


def format_remaining_time(remaining_seconds: float) -> str:
    """Formats remaining seconds into mm:ss."""
    rem = max(0, int(remaining_seconds))
    mins, secs = divmod(rem, 60)
    return f"{mins}m {secs:02d}s"


async def block_timer_completed_callback(context: ContextTypes.DEFAULT_TYPE):
    """Callback executed when a focus block countdown finishes."""
    job_data = context.job.data
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    duration_mins = job_data["duration_mins"]
    session_type = job_data.get("session_type", "general")
    topic = job_data.get("topic", "Deep Work")

    # Remove from active timers
    if user_id in active_timers:
        del active_timers[user_id]

    # Record block in database
    session_date = job_data.get("session_date")
    result = database.record_completed_block(
        duration_mins=duration_mins,
        session_date=session_date,
        topic=topic,
        tz_name=TIMEZONE_NAME,
        db_path=DB_PATH,
    )

    block_num = result["block_number"]
    today_blocks = result["today_blocks"]
    today_mins = result["today_minutes"]
    curr_streak = result["current_streak"]
    streak_broken = result["streak_broken"]
    lost_count = result["lost_streak_count"]

    streak_badge = f"🔥 <b>Day {curr_streak}</b>"
    if streak_broken and lost_count > 0:
        streak_note = (
            f"\n\n<i>⚠️ Streak reset (lost {lost_count} days). New streak started today!</i>"
        )
    else:
        streak_note = ""

    # Contextual closing message
    closing_note = ""
    if session_type == "block1" or block_num == 1:
        closing_note = (
            "\n\n🚶‍♂️ <b>Rack the weight! Head to office.</b>\n"
            "Your brain will digest the Namaste DSA concepts in transit (diffuse mode)."
        )
    elif session_type == "block2" or block_num == 2:
        closing_note = (
            "\n\n💼 <b>11:00 AM Bell! Slack Shield Unlocked.</b>\n"
            "Open Slack and corporate email. Your day's core growth is already won guilt-free!"
        )

    msg = (
        f"🔔 <b>Ding! {duration_mins} minutes up!</b>\n\n"
        f"✅ <b>Block {block_num} completed ({topic}).</b>\n"
        f"📊 <b>Today's Total:</b> {today_blocks} block(s) ({today_mins} mins deep work)\n"
        f"🏆 <b>Streak:</b> {streak_badge}{streak_note}{closing_note}"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=msg,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(),
    )


async def start_focus_block(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    duration_mins: int,
    session_type: str = "general",
    topic: str = "Deep Work",
):
    """Core routine to schedule and lock in a focus block."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    now = datetime.now(TIMEZONE)

    # Active timer guard
    if user.id in active_timers:
        current_timer = active_timers[user.id]
        end_time_val = current_timer["end_time"]
        now_cmp = datetime.now(TIMEZONE) if end_time_val.tzinfo else datetime.now()
        remaining = (end_time_val - now_cmp).total_seconds()
        rem_str = format_remaining_time(remaining)
        await reply(
            update,
            f"⚠️ <b>Active block already in progress!</b>\n"
            f"Block {current_timer['block_number']} ({current_timer.get('topic', 'Deep Work')}) has <b>{rem_str}</b> remaining.\n\n"
            f"Use /stop to cancel the active timer if you need to abort.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard(),
        )
        return

    # Determine logical session date (supports late-night sessions and protects start date)
    session_date = database.get_logical_date(dt=now, tz_name=TIMEZONE_NAME, db_path=DB_PATH)
    next_block_num = database.get_next_block_number(session_date, db_path=DB_PATH)

    end_time = now + timedelta(minutes=duration_mins)

    # Schedule completion job in PTB job_queue
    job = context.job_queue.run_once(
        block_timer_completed_callback,
        when=duration_mins * 60,
        data={
            "user_id": user.id,
            "chat_id": chat_id,
            "duration_mins": duration_mins,
            "block_number": next_block_num,
            "session_type": session_type,
            "session_date": session_date,
            "topic": topic,
        },
        name=f"timer_{user.id}_{int(now.timestamp())}",
    )

    active_timers[user.id] = {
        "job": job,
        "block_number": next_block_num,
        "duration_mins": duration_mins,
        "start_time": now,
        "end_time": end_time,
        "session_type": session_type,
        "session_date": session_date,
        "topic": topic,
    }

    # Construct lock-in message
    slack_shield_active = (
        session_type == "block2"
        or next_block_num == 2
        or (now.hour == 10 and 20 <= now.minute <= 45)
    )

    shield_text = ""
    if slack_shield_active:
        shield_text = (
            "\n\n🛡️ <b>SLACK SHIELD ACTIVATED</b>\n"
            "Rule: Keep Slack, Microsoft Teams, and Outlook closed until the 11:00 AM bell rings!"
        )

    title_desc = "Block"
    if session_type == "block1":
        title_desc = "Block 1 (Theory / Namaste DSA)"
    elif session_type == "block2":
        title_desc = "Block 2 (Hands-on Code / Assignment)"
    elif next_block_num > 2:
        title_desc = f"Block {next_block_num} (Bonus Rep)"
    else:
        title_desc = f"Block {next_block_num}"

    msg = (
        f"👀 <b>Spotter locked in for {title_desc}.</b>\n\n"
        f"🎯 <b>Topic:</b> {topic}\n"
        f"⏱️ <b>Timer:</b> {duration_mins} minutes\n"
        f"📱 <b>Protocol:</b> Phone face-down. I'm watching the clock. Lock in.{shield_text}"
    )

    await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())


# ---------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------

@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends welcome message and bot commands menu with one-tap action buttons."""
    msg = (
        "🏋️‍♂️ <b>Welcome to Tech Spotter!</b>\n\n"
        "I am your digital body double and consistency engine for mastering DSA and side projects.\n\n"
        "<b>Core Routine Commands:</b>\n"
        "• <code>/block [mins] [topic]</code> - Focus block (e.g. <code>/block 15 Trees</code>)\n"
        "• <code>/block1 [topic]</code> - 30m Theory (Home Desk - Namaste DSA)\n"
        "• <code>/block2 [topic]</code> - 30m Code + 🛡️ Slack Shield (Office Desk)\n"
        "• <code>/stop</code> - Cancel current active timer (discards block)\n\n"
        "<b>Consistency & Recovery:</b>\n"
        "• <code>/status</code> - Live timer, today's blocks & streak status\n"
        "• <code>/history</code> - Past 7 days breakdown with topics\n"
        "• <code>/weekly</code> - Full weekly summary & consistency score\n"
        "• <code>/freeze [reason]</code> - Use your 1 weekly rest day without losing streak\n"
        "• <code>/health</code> - Diagnostic connection & DB test\n\n"
        "<i>Tap a quick button below to lock in immediately:</i>"
    )
    await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())


@restricted
async def cmd_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts a focus block. Accepts optional minutes and topic (e.g., /block 15 Trees, /block 45)."""
    duration = 30
    topic = "Deep Work"

    if context.args:
        first_arg = context.args[0]
        try:
            val = int(first_arg)
            if 1 <= val <= 240:
                duration = val
                if len(context.args) > 1:
                    topic = " ".join(context.args[1:])
            else:
                await reply(update, "⚠️ Duration must be between 1 and 240 minutes.")
                return
        except ValueError:
            # First arg was a topic name rather than a number (e.g. /block Trees)
            topic = " ".join(context.args)

    await start_focus_block(update, context, duration_mins=duration, session_type="general", topic=topic)


@restricted
async def cmd_block1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts Block 1: 30 minutes Theory (Namaste DSA). Accepts optional topic."""
    duration = 30
    topic = "Namaste DSA (Theory)"
    if context.args:
        try:
            val = int(context.args[0])
            if 1 <= val <= 240:
                duration = val
                if len(context.args) > 1:
                    topic = f"Namaste DSA: {' '.join(context.args[1:])}"
            else:
                topic = f"Namaste DSA: {' '.join(context.args)}"
        except ValueError:
            topic = f"Namaste DSA: {' '.join(context.args)}"

    await start_focus_block(update, context, duration_mins=duration, session_type="block1", topic=topic)


@restricted
async def cmd_block2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts Block 2: 30 minutes Code with Slack Shield enforcement. Accepts optional topic."""
    duration = 30
    topic = "Namaste DSA (Code)"
    if context.args:
        try:
            val = int(context.args[0])
            if 1 <= val <= 240:
                duration = val
                if len(context.args) > 1:
                    topic = f"Namaste DSA: {' '.join(context.args[1:])}"
            else:
                topic = f"Namaste DSA: {' '.join(context.args)}"
        except ValueError:
            topic = f"Namaste DSA: {' '.join(context.args)}"

    await start_focus_block(update, context, duration_mins=duration, session_type="block2", topic=topic)


@restricted
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels an ongoing block timer prematurely. Discards the block per protocol."""
    user = update.effective_user
    if user.id not in active_timers:
        await reply(update, "💤 No active block timer is running.", reply_markup=get_main_keyboard())
        return

    timer_info = active_timers.pop(user.id)
    job = timer_info["job"]
    if job:
        job.schedule_removal()

    block_num = timer_info["block_number"]
    topic = timer_info.get("topic", "Deep Work")
    await reply(
        update,
        f"🛑 <b>Block {block_num} ({topic}) cancelled.</b>\n"
        f"Timer stopped. No minutes logged. Rest and reset for the next rep.",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(),
    )


@restricted
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows live status: active countdown (if any), today's totals, streak, and rest days."""
    user = update.effective_user
    status = database.get_status(tz_name=TIMEZONE_NAME, db_path=DB_PATH)

    now = datetime.now(TIMEZONE)

    # Active timer line
    if user.id in active_timers:
        current = active_timers[user.id]
        end_time_val = current["end_time"]
        now_cmp = datetime.now(TIMEZONE) if end_time_val.tzinfo else datetime.now()
        rem = (end_time_val - now_cmp).total_seconds()
        rem_str = format_remaining_time(rem)
        timer_text = (
            f"⏱️ <b>Active:</b> Block {current['block_number']} ({current.get('topic', 'Deep Work')})\n"
            f"   ⏳ <b>Remaining:</b> {rem_str}"
        )
    else:
        timer_text = "💤 <b>Active:</b> No timer running"

    today_blocks = status["today_blocks"]
    today_mins = status["today_minutes"]
    current_streak = status["current_streak"]
    longest_streak = status["longest_streak"]
    is_broken = status["is_streak_broken"]
    completed_today = status["completed_today"]
    in_grace = status.get("in_grace_period", False)
    has_active_timer = (user.id in active_timers)

    if is_broken:
        streak_display = "0 🔥 (Broken - Missed yesterday, start a new streak today!)"
    elif in_grace:
        streak_display = f"Day {current_streak} 🔥 (🌙 Late-night grace window until 04:00 AM)"
    elif current_streak == 0:
        if has_active_timer:
            streak_display = "Igniting today! 🔥 (Active block in progress)"
        else:
            streak_display = "0 (Complete a block today to ignite your streak!)"
    else:
        if completed_today:
            streak_status = "✅ Completed today"
        elif has_active_timer:
            streak_status = "⏳ Active block in progress"
        else:
            streak_status = "⏳ Pending today"
        streak_display = f"Day {current_streak} 🔥 ({streak_status})"

    freeze_note = ""
    if status.get("freeze_used_this_week"):
        freeze_note = f"\n🧊 <b>Weekly Rest Day:</b> Used on {status.get('last_freeze_date')}"
    else:
        freeze_note = "\n🧊 <b>Weekly Rest Day:</b> 1 available (/freeze)"

    msg = (
        f"📊 <b>Tech Spotter Live Status</b>\n"
        f"🗓️ <b>Date:</b> {status['today_date']}\n\n"
        f"{timer_text}\n\n"
        f"📦 <b>Today:</b> {today_blocks} completed ({today_mins} mins)\n"
        f"🔥 <b>Current Streak:</b> {streak_display}\n"
        f"🏆 <b>Best Streak:</b> {longest_streak} days{freeze_note}\n"
        f"📈 <b>Lifetime:</b> {status['total_blocks_completed']} blocks | {status['total_minutes_completed']} mins"
    )

    await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())


@restricted
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows history of completed blocks and topics over the last 7 days."""
    history = database.get_history(days=7, tz_name=TIMEZONE_NAME, db_path=DB_PATH)

    lines = []
    total_week_blocks = 0
    total_week_mins = 0

    for day in history:
        blocks = day["blocks"]
        mins = day["total_mins"]
        total_week_blocks += blocks
        total_week_mins += mins

        badge = "🔥" if blocks > 0 else "⚪"
        topic_suffix = f" — <i>{day['topics']}</i>" if day.get("topics") else ""
        lines.append(f"{badge} <code>{day['date']}</code>: {blocks} block(s) ({mins} mins){topic_suffix}")

    msg = (
        "📅 <b>Past 7 Days History</b>\n\n"
        + "\n".join(lines)
        + f"\n\n<b>Weekly Total:</b> {total_week_blocks} blocks | {total_week_mins} mins deep work"
    )

    await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())


@restricted
async def cmd_freeze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Applies a weekly streak freeze / rest day to protect streak."""
    reason = "Rest Day"
    if context.args:
        reason = " ".join(context.args)

    result = database.apply_streak_freeze(reason=reason, tz_name=TIMEZONE_NAME, db_path=DB_PATH)
    if result["ok"]:
        msg = (
            f"🧊 <b>Streak Freeze Activated!</b>\n\n"
            f"🗓️ <b>Date:</b> {result['date']}\n"
            f"🛡️ <b>Status:</b> Streak of {result['current_streak']} day(s) is protected!\n"
            f"📝 <b>Reason:</b> {result['reason']}\n\n"
            f"<i>Rest and recovery are just as essential as training. Enjoy your rest day!</i>"
        )
    else:
        msg = f"⚠️ <b>Rest Day Already Used</b>\n\n{result['message']}"

    await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())


@restricted
async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows current week's deep work summary, topics, and consistency score."""
    summary = database.get_weekly_summary(tz_name=TIMEZONE_NAME, db_path=DB_PATH)

    topics_str = ", ".join(summary["topics"]) if summary["topics"] else "Deep Work"
    freeze_note = ""
    if summary["freezes_used"] > 0:
        freeze_note = f"\n🧊 <b>Rest Days Used:</b> {summary['freezes_used']}/1 (Protected on {summary['last_freeze_date']})"
    else:
        freeze_note = "\n🧊 <b>Rest Days:</b> 1 available this week (/freeze)"

    score = summary["consistency_pct"]
    if score >= 85:
        tier = "🏆 Elite Tier (Unstoppable)"
    elif score >= 60:
        tier = "🔥 Solid Consistency"
    else:
        tier = "⚡ In Progress (Keep showing up)"

    msg = (
        f"📈 <b>Weekly Consistency Recap</b>\n"
        f"🗓️ <b>Week:</b> <code>{summary['week_start']}</code> to <code>{summary['week_end']}</code>\n\n"
        f"⏱️ <b>Total Deep Work:</b> {summary['total_hours']} hrs ({summary['total_mins']} mins)\n"
        f"📦 <b>Completed Blocks:</b> {summary['total_blocks']} block(s)\n"
        f"🎯 <b>Topics Covered:</b> {topics_str}\n"
        f"🔥 <b>Active Days:</b> {summary['active_days']} / 7 days\n"
        f"📊 <b>Consistency Score:</b> {score}% — {tier}{freeze_note}\n\n"
        f"<i>Small daily reps compound into mastery. Let's conquer the upcoming week!</i>"
    )
    await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())


@restricted
async def cmd_breaks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the audit log of broken streaks."""
    breaks = database.get_breaks(limit=10, db_path=DB_PATH)

    if not breaks:
        msg = "✨ <b>Streak Break Audit Log</b>\n\nNo broken streaks recorded yet! Keep the chain unbroken."
        await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())
        return

    lines = []
    for b in breaks:
        lines.append(
            f"⚠️ <b>{b['broken_on_date']}</b>: Lost {b['lost_streak_count']}-day streak ({b['notes']})"
        )

    msg = "📉 <b>Streak Break Audit Log</b>\n\n" + "\n".join(lines)
    await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())


@restricted
async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Diagnostic command to check bot operational status,
    database read/write access, active timers, and timezone.
    """
    db_health = database.check_db_health(db_path=DB_PATH)
    now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    if db_health["ok"]:
        db_status = (
            f"✅ Connected\n"
            f"   • Database: <code>{db_health['db_path']}</code>\n"
            f"   • Total Logged Blocks: {db_health['daily_logs_count']}\n"
            f"   • Recorded Breaks: {db_health['breaks_count']}"
        )
    else:
        db_status = f"❌ Error: {db_health['error']}"

    active_count = len(active_timers)

    msg = (
        f"🩺 <b>Tech Spotter Health & Diagnostics</b>\n\n"
        f"🤖 <b>Bot Status:</b> Online & Responding\n"
        f"💾 <b>Database:</b>\n{db_status}\n"
        f"⏱️ <b>Active Timers:</b> {active_count}\n"
        f"🌍 <b>Timezone:</b> {TIMEZONE_NAME} ({now})\n"
        f"🔒 <b>Authorized User:</b> <code>{AUTHORIZED_USER_ID}</code>"
    )

    await reply(update, msg, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard())


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles interactive inline button clicks."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user or AUTHORIZED_USER_ID is None or user.id != AUTHORIZED_USER_ID:
        return

    data = query.data
    if data == "block_15":
        await start_focus_block(update, context, duration_mins=15, session_type="general", topic="Deep Work")
    elif data == "block_30":
        await start_focus_block(update, context, duration_mins=30, session_type="general", topic="Deep Work")
    elif data == "block_45":
        await start_focus_block(update, context, duration_mins=45, session_type="general", topic="Deep Work")
    elif data == "block_60":
        await start_focus_block(update, context, duration_mins=60, session_type="general", topic="Bonus Rep")
    elif data == "block_b1":
        await start_focus_block(update, context, duration_mins=30, session_type="block1", topic="Namaste DSA (Theory)")
    elif data == "block_b2":
        await start_focus_block(update, context, duration_mins=30, session_type="block2", topic="Namaste DSA (Code)")
    elif data == "action_status":
        await cmd_status(update, context)
    elif data == "action_history":
        await cmd_history(update, context)
    elif data == "action_weekly":
        await cmd_weekly(update, context)
    elif data == "action_stop":
        await cmd_stop(update, context)
    elif data == "action_freeze":
        await cmd_freeze(update, context)


# ---------------------------------------------------------
# Automated Scheduled Jobs
# ---------------------------------------------------------

async def scheduled_sleep_reminder(context: ContextTypes.DEFAULT_TYPE):
    """10:00 PM daily gentle sleep reminder for 7-hour rest before 06:00 AM gym."""
    if AUTHORIZED_USER_ID:
        msg = (
            "🌙 <b>10:00 PM: Wind-Down Reminder</b>\n\n"
            "Great work today! Shut down screens and prepare for sleep.\n"
            "Aim for 7 hours of rest so you are refreshed for tomorrow's 06:00 AM gym session. 💤"
        )
        try:
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=msg,
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard(),
            )
        except Exception as e:
            logger.error("Failed to send sleep reminder: %s", e)


async def scheduled_sunday_digest(context: ContextTypes.DEFAULT_TYPE):
    """Sunday 08:00 PM weekly summary digest."""
    if AUTHORIZED_USER_ID:
        summary = database.get_weekly_summary(tz_name=TIMEZONE_NAME, db_path=DB_PATH)
        topics_str = ", ".join(summary["topics"]) if summary["topics"] else "Deep Work"
        score = summary["consistency_pct"]
        msg = (
            f"📈 <b>Sunday Night Weekly Digest</b>\n\n"
            f"Here is your consistency report for this week:\n"
            f"• <b>Total Deep Work:</b> {summary['total_hours']} hours ({summary['total_blocks']} blocks)\n"
            f"• <b>Active Consistency:</b> {summary['active_days']}/7 days ({score}%)\n"
            f"• <b>Topics Covered:</b> {topics_str}\n\n"
            f"Rest well tonight. Get ready to attack your Namaste DSA reps tomorrow! 🚀"
        )
        try:
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=msg,
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard(),
            )
        except Exception as e:
            logger.error("Failed to send Sunday digest: %s", e)


def setup_scheduled_jobs(application: Application):
    """Configures daily and weekly scheduled notifications in JobQueue."""
    job_queue = application.job_queue
    if not job_queue:
        logger.warning("JobQueue is not enabled in this Application instance.")
        return

    # 10:00 PM IST (22:00) - Sleep reminder
    job_queue.run_daily(
        scheduled_sleep_reminder,
        time=time(hour=22, minute=0, tzinfo=TIMEZONE),
        name="daily_nudge_2200",
    )

    # Sunday 08:00 PM IST (20:00) - Weekly Digest
    job_queue.run_daily(
        scheduled_sunday_digest,
        time=time(hour=20, minute=0, tzinfo=TIMEZONE),
        days=(6,),  # 6 = Sunday in PTB
        name="weekly_sunday_digest",
    )
    logger.info("Daily sleep reminder (22:00) and Sunday digest (20:00) configured for %s", TIMEZONE_NAME)


def build_application() -> Application:
    """Builds and returns the configured Telegram bot Application."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is not configured! Please set it in your .env file."
        )

    # Initialize SQLite database
    database.init_db(DB_PATH)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("block", cmd_block))
    app.add_handler(CommandHandler("block1", cmd_block1))
    app.add_handler(CommandHandler("block2", cmd_block2))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("breaks", cmd_breaks))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("ping", cmd_health))
    app.add_handler(CommandHandler("freeze", cmd_freeze))
    app.add_handler(CommandHandler("rest", cmd_freeze))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("summary", cmd_weekly))

    # Register CallbackQueryHandler for interactive buttons
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Setup daily & weekly scheduled jobs
    setup_scheduled_jobs(app)

    return app


def main():
    """Main application entrypoint."""
    logger.info("Initializing Tech Spotter Bot...")
    if AUTHORIZED_USER_ID is None:
        logger.warning(
            "TELEGRAM_USER_ID is not configured in .env! All incoming commands will be ignored."
        )
    else:
        logger.info("Whitelisted user ID: %s", AUTHORIZED_USER_ID)

    try:
        app = build_application()
        logger.info("Starting polling loop...")
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error("Fatal error starting bot: %s", e)
        raise


if __name__ == "__main__":
    main()
