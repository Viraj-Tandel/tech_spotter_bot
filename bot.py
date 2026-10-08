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
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
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
# user_id -> {"job": Job, "block_number": int, "duration_mins": int, "start_time": datetime, "end_time": datetime, "session_type": str}
active_timers: Dict[int, Dict[str, Any]] = {}


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

    # Remove from active timers
    if user_id in active_timers:
        del active_timers[user_id]

    # Record block in database
    result = database.record_completed_block(
        duration_mins=duration_mins,
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
        f"✅ <b>Block {block_num} completed.</b>\n"
        f"📊 <b>Today's Total:</b> {today_blocks} block(s) ({today_mins} mins deep work)\n"
        f"🏆 <b>Streak:</b> {streak_badge}{streak_note}{closing_note}"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=msg,
        parse_mode=ParseMode.HTML,
    )


async def start_focus_block(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    duration_mins: int,
    session_type: str = "general",
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
        await update.message.reply_text(
            f"⚠️ <b>Active block already in progress!</b>\n"
            f"Block {current_timer['block_number']} has <b>{rem_str}</b> remaining.\n\n"
            f"Use /stop to cancel the active timer if you need to abort.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Determine next block number for today
    today_str = database.get_today_date(TIMEZONE_NAME)
    next_block_num = database.get_next_block_number(today_str, db_path=DB_PATH)

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
        f"⏱️ <b>Timer:</b> {duration_mins} minutes\n"
        f"📱 <b>Protocol:</b> Phone face-down. I'm watching the clock. Lock in.{shield_text}"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------

@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends welcome message and bot commands menu."""
    msg = (
        "🏋️‍♂️ <b>Welcome to Tech Spotter!</b>\n\n"
        "I am your digital body double and consistency engine for mastering DSA and side projects.\n\n"
        "<b>Core Routine Commands:</b>\n"
        "• <code>/block1</code> - 30 min Theory (Home Desk - Namaste DSA)\n"
        "• <code>/block2</code> - 30 min Code + 🛡️ Slack Shield (Office Desk)\n"
        "• <code>/block [mins]</code> - Custom focus block (default: 30 mins)\n"
        "• <code>/stop</code> - Cancel current active timer (discards block)\n\n"
        "<b>Tracking & Insights:</b>\n"
        "• <code>/status</code> - Live timer, today's blocks & streak status\n"
        "• <code>/history</code> - Past 7 days breakdown\n"
        "• <code>/breaks</code> - Streak break audit trail\n"
        "• <code>/health</code> - Diagnostic connection & DB test\n\n"
        "<i>Consistency beats motivation. Let's rack up the reps.</i>"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts a focus block. Accepts optional minutes argument (e.g., /block 45)."""
    duration = 30
    if context.args:
        try:
            val = int(context.args[0])
            if 1 <= val <= 240:
                duration = val
            else:
                await update.message.reply_text("⚠️ Duration must be between 1 and 240 minutes.")
                return
        except ValueError:
            await update.message.reply_text("⚠️ Invalid duration. Usage: <code>/block [minutes]</code>", parse_mode=ParseMode.HTML)
            return

    await start_focus_block(update, context, duration_mins=duration, session_type="general")


@restricted
async def cmd_block1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts Block 1: 30 minutes Theory (Namaste DSA)."""
    duration = 30
    if context.args:
        try:
            val = int(context.args[0])
            if 1 <= val <= 240:
                duration = val
        except ValueError:
            pass
    await start_focus_block(update, context, duration_mins=duration, session_type="block1")


@restricted
async def cmd_block2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts Block 2: 30 minutes Code with Slack Shield enforcement."""
    duration = 30
    if context.args:
        try:
            val = int(context.args[0])
            if 1 <= val <= 240:
                duration = val
        except ValueError:
            pass
    await start_focus_block(update, context, duration_mins=duration, session_type="block2")


@restricted
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels an ongoing block timer prematurely. Discards the block per protocol."""
    user = update.effective_user
    if user.id not in active_timers:
        await update.message.reply_text("💤 No active block timer is running.")
        return

    timer_info = active_timers.pop(user.id)
    job = timer_info["job"]
    if job:
        job.schedule_removal()

    block_num = timer_info["block_number"]
    await update.message.reply_text(
        f"🛑 <b>Block {block_num} cancelled.</b>\n"
        f"Timer stopped. No minutes logged. Rest and reset for the next rep.",
        parse_mode=ParseMode.HTML,
    )


@restricted
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows live status: active countdown (if any), today's totals, streak."""
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
        timer_text = f"⏱️ <b>Active:</b> Block {current['block_number']} ({rem_str} remaining)"
    else:
        timer_text = "💤 <b>Active:</b> No timer running"

    today_blocks = status["today_blocks"]
    today_mins = status["today_minutes"]
    current_streak = status["current_streak"]
    longest_streak = status["longest_streak"]
    is_broken = status["is_streak_broken"]
    completed_today = status["completed_today"]

    if is_broken:
        streak_display = "0 🔥 (Broken - Missed yesterday, start a new streak today!)"
    elif current_streak == 0:
        streak_display = "0 (Complete a block today to ignite your streak!)"
    else:
        streak_status = "✅ Completed today" if completed_today else "⏳ Pending today"
        streak_display = f"Day {current_streak} 🔥 ({streak_status})"

    msg = (
        f"📊 <b>Tech Spotter Live Status</b>\n"
        f"🗓️ <b>Date:</b> {status['today_date']}\n\n"
        f"{timer_text}\n\n"
        f"📦 <b>Today:</b> {today_blocks} completed ({today_mins} mins)\n"
        f"🔥 <b>Current Streak:</b> {streak_display}\n"
        f"🏆 <b>Best Streak:</b> {longest_streak} days\n"
        f"📈 <b>Lifetime:</b> {status['total_blocks_completed']} blocks | {status['total_minutes_completed']} mins"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows history of completed blocks over the last 7 days."""
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
        lines.append(f"{badge} <code>{day['date']}</code>: {blocks} block(s) ({mins} mins)")

    msg = (
        "📅 <b>Past 7 Days History</b>\n\n"
        + "\n".join(lines)
        + f"\n\n<b>Weekly Total:</b> {total_week_blocks} blocks | {total_week_mins} mins deep work"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_breaks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the audit log of broken streaks."""
    breaks = database.get_breaks(limit=10, db_path=DB_PATH)

    if not breaks:
        msg = "✨ <b>Streak Break Audit Log</b>\n\nNo broken streaks recorded yet! Keep the chain unbroken."
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    lines = []
    for b in breaks:
        lines.append(
            f"⚠️ <b>{b['broken_on_date']}</b>: Lost {b['lost_streak_count']}-day streak ({b['notes']})"
        )

    msg = "📉 <b>Streak Break Audit Log</b>\n\n" + "\n".join(lines)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


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

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------
# Automated Scheduled Nudges
# ---------------------------------------------------------

async def scheduled_morning_block1(context: ContextTypes.DEFAULT_TYPE):
    """09:45 AM daily nudge for Block 1 (Theory / Namaste DSA)."""
    if AUTHORIZED_USER_ID:
        msg = (
            "⏰ <b>09:45 AM: Morning Study Window Open!</b>\n\n"
            "Post-gym protein shake and shower done? Your brain is primed with endorphins.\n"
            "Ready for <b>Block 1 (Namaste DSA Video / Theory)</b>?\n\n"
            "Send <code>/block1</code> to lock in."
        )
        try:
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=msg,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error("Failed to send morning Block 1 nudge: %s", e)


async def scheduled_morning_block2(context: ContextTypes.DEFAULT_TYPE):
    """10:30 AM daily nudge for Block 2 (Code / Slack Shield)."""
    if AUTHORIZED_USER_ID:
        msg = (
            "⏰ <b>10:30 AM: Office Desk Arrival!</b>\n\n"
            "Grab your coffee. Keep Slack and Outlook closed.\n"
            "Ready for <b>Block 2 (Hands-on Code / Assignment)</b>?\n\n"
            "Send <code>/block2</code> to lock in with 🛡️ <b>Slack Shield</b>."
        )
        try:
            await context.bot.send_message(
                chat_id=AUTHORIZED_USER_ID,
                text=msg,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error("Failed to send morning Block 2 nudge: %s", e)


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
            )
        except Exception as e:
            logger.error("Failed to send sleep reminder: %s", e)


def setup_scheduled_jobs(application: Application):
    """Configures daily scheduled notifications in JobQueue."""
    job_queue = application.job_queue
    if not job_queue:
        logger.warning("JobQueue is not enabled in this Application instance.")
        return

    # 09:45 AM IST
    job_queue.run_daily(
        scheduled_morning_block1,
        time=time(hour=9, minute=45, tzinfo=TIMEZONE),
        name="daily_nudge_0945",
    )

    # 10:30 AM IST
    job_queue.run_daily(
        scheduled_morning_block2,
        time=time(hour=10, minute=30, tzinfo=TIMEZONE),
        name="daily_nudge_1030",
    )

    # 10:00 PM IST (22:00)
    job_queue.run_daily(
        scheduled_sleep_reminder,
        time=time(hour=22, minute=0, tzinfo=TIMEZONE),
        name="daily_nudge_2200",
    )
    logger.info("Daily scheduled nudges configured for 09:45, 10:30, and 22:00 %s", TIMEZONE_NAME)


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
    app.add_handler(CommandHandler("block", cmd_block))
    app.add_handler(CommandHandler("block1", cmd_block1))
    app.add_handler(CommandHandler("block2", cmd_block2))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("breaks", cmd_breaks))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("ping", cmd_health))

    # Setup daily scheduled jobs
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
