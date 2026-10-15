"""
database.py - SQLite storage engine for Tech Spotter Telegram Bot.
Handles daily block logs, streak management, and streak break audit trails.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pytz

DEFAULT_DB_PATH = "spotter.db"
DEFAULT_TIMEZONE = "Asia/Kolkata"


@contextmanager
def get_db_connection(db_path: str = DEFAULT_DB_PATH):
    """Context manager ensuring connection is always closed after use."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initializes SQLite schema and ensures singleton streak state exists."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Table 1: Log every completed focus block
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                duration_mins INTEGER NOT NULL,
                topic TEXT DEFAULT 'Deep Work',
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Migration: ensure 'topic' column exists for existing databases
        cursor.execute("PRAGMA table_info(daily_logs)")
        cols = [r["name"] for r in cursor.fetchall()]
        if "topic" not in cols:
            cursor.execute("ALTER TABLE daily_logs ADD COLUMN topic TEXT DEFAULT 'Deep Work'")

        # Table 2: Singleton table tracking live streak status
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS streak_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_streak INTEGER DEFAULT 0,
                longest_streak INTEGER DEFAULT 0,
                last_active_date TEXT,
                total_blocks_completed INTEGER DEFAULT 0,
                total_minutes_completed INTEGER DEFAULT 0
            );
            """
        )

        # Table 3: Audit log recording every broken streak event
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS streak_break_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broken_on_date TEXT NOT NULL,
                lost_streak_count INTEGER NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT DEFAULT 'Missed daily block'
            );
            """
        )

        # Table 4: Track weekly streak freeze / rest days (max 1 per calendar week)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS streak_freezes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                reason TEXT DEFAULT 'Rest day',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Initialize singleton row in streak_state if missing
        cursor.execute(
            """
            INSERT OR IGNORE INTO streak_state (
                id, current_streak, longest_streak, last_active_date, 
                total_blocks_completed, total_minutes_completed
            ) VALUES (1, 0, 0, NULL, 0, 0);
            """
        )
        conn.commit()


def get_today_date(tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Returns today's date formatted as YYYY-MM-DD in the target timezone."""
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).strftime("%Y-%m-%d")


def get_logical_date(
    dt: Optional[datetime] = None,
    tz_name: str = DEFAULT_TIMEZONE,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """
    Returns the logical date for habit tracking.
    If a session is initiated between 00:00 and 04:00 AM,
    and yesterday has no recorded blocks, it attributes to yesterday (late-night grace period).
    Otherwise, returns the calendar date in target timezone.
    """
    tz = pytz.timezone(tz_name)
    now_dt = dt or datetime.now(tz)
    calendar_date_str = now_dt.strftime("%Y-%m-%d")
    current_date = now_dt.date()

    if 0 <= now_dt.hour < 4:
        yesterday_str = (current_date - timedelta(days=1)).strftime("%Y-%m-%d")
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM daily_logs WHERE date = ?",
                (yesterday_str,),
            )
            count = cursor.fetchone()[0]
            if count == 0:
                return yesterday_str

    return calendar_date_str


def get_next_block_number(today_str: str, db_path: str = DEFAULT_DB_PATH) -> int:
    """Returns the next block number (1, 2, 3...) for the specified date."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(block_number), 0) + 1 FROM daily_logs WHERE date = ?",
            (today_str,),
        )
        row = cursor.fetchone()
        return row[0] if row else 1


def record_completed_block(
    duration_mins: int,
    session_date: Optional[str] = None,
    topic: str = "Deep Work",
    tz_name: str = DEFAULT_TIMEZONE,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Records a completed focus block and evaluates streak preservation or break.
    If session_date is provided (e.g. from when block was initiated), it uses that date
    to prevent midnight rollovers from breaking late-night study sessions.
    Completing a single block (e.g. 15 or 30 mins) is sufficient to increment/preserve streak.
    """
    if session_date:
        today_str = session_date
    else:
        today_str = get_logical_date(tz_name=tz_name, db_path=db_path)

    today_date = datetime.strptime(today_str, "%Y-%m-%d").date()

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Fetch streak state
        cursor.execute(
            """
            SELECT current_streak, longest_streak, last_active_date,
                   total_blocks_completed, total_minutes_completed
            FROM streak_state WHERE id = 1
            """
        )
        state = cursor.fetchone()
        curr_streak = state["current_streak"]
        long_streak = state["longest_streak"]
        last_active = state["last_active_date"]
        total_blocks = state["total_blocks_completed"]
        total_mins = state["total_minutes_completed"]

        streak_broken = False
        lost_streak_count = 0

        if last_active is None:
            # First block ever
            new_curr_streak = 1
            new_long_streak = 1
        else:
            last_date = datetime.strptime(last_active, "%Y-%m-%d").date()
            delta_days = (today_date - last_date).days

            if delta_days == 0:
                # Same day: additional block; streak count stays the same
                new_curr_streak = curr_streak
                new_long_streak = long_streak
            elif delta_days == 1:
                # Consecutive day: increment streak
                new_curr_streak = curr_streak + 1
                new_long_streak = max(long_streak, new_curr_streak)
            elif delta_days < 0:
                # Completed for an earlier date (e.g. night-owl backfill)
                new_curr_streak = max(curr_streak, 1)
                new_long_streak = max(long_streak, new_curr_streak)
            else:
                # Streak broken (delta_days > 1)
                streak_broken = True
                lost_streak_count = curr_streak
                yesterday_str = (today_date - timedelta(days=1)).strftime("%Y-%m-%d")

                # Insert into break audit log if there was an active streak lost
                if curr_streak > 0:
                    cursor.execute(
                        """
                        INSERT INTO streak_break_log (broken_on_date, lost_streak_count, notes)
                        VALUES (?, ?, ?)
                        """,
                        (yesterday_str, lost_streak_count, f"Missed {delta_days - 1} day(s) before {today_str}"),
                    )

                # Reset to 1 since user completed a block today
                new_curr_streak = 1
                new_long_streak = max(long_streak, 1)

        # Get next block number for today
        cursor.execute(
            "SELECT COALESCE(MAX(block_number), 0) + 1 FROM daily_logs WHERE date = ?",
            (today_str,),
        )
        block_number = cursor.fetchone()[0]

        # Log block with topic
        cursor.execute(
            """
            INSERT INTO daily_logs (date, block_number, duration_mins, topic)
            VALUES (?, ?, ?, ?)
            """,
            (today_str, block_number, duration_mins, topic),
        )

        # Update streak_state
        # Only advance last_active_date if today_str is newer than last_active
        effective_last_active = today_str
        if last_active and last_date > today_date:
            effective_last_active = last_active

        cursor.execute(
            """
            UPDATE streak_state
            SET current_streak = ?,
                longest_streak = ?,
                last_active_date = ?,
                total_blocks_completed = ?,
                total_minutes_completed = ?
            WHERE id = 1
            """,
            (
                new_curr_streak,
                new_long_streak,
                effective_last_active,
                total_blocks + 1,
                total_mins + duration_mins,
            ),
        )

        # Query today's totals
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(duration_mins), 0) FROM daily_logs WHERE date = ?",
            (today_str,),
        )
        today_totals = cursor.fetchone()
        today_blocks = today_totals[0]
        today_mins = today_totals[1]

        conn.commit()

        return {
            "block_number": block_number,
            "duration_mins": duration_mins,
            "today_blocks": today_blocks,
            "today_minutes": today_mins,
            "current_streak": new_curr_streak,
            "longest_streak": new_long_streak,
            "streak_broken": streak_broken,
            "lost_streak_count": lost_streak_count,
            "session_date": today_str,
            "topic": topic,
        }


def get_status(
    tz_name: str = DEFAULT_TIMEZONE,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Returns live status metrics. Dynamically calculates if a streak has broken:
    If last_active_date is >= 2 days ago, effective current streak is 0,
    unless within the night-owl grace window (00:00 - 04:00 AM).
    """
    tz = pytz.timezone(tz_name)
    now_dt = datetime.now(tz)
    today_str = now_dt.strftime("%Y-%m-%d")
    today_date = now_dt.date()
    is_night_owl = (0 <= now_dt.hour < 4)

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT current_streak, longest_streak, last_active_date,
                   total_blocks_completed, total_minutes_completed
            FROM streak_state WHERE id = 1
            """
        )
        state = cursor.fetchone()
        curr_streak = state["current_streak"] if state else 0
        long_streak = state["longest_streak"] if state else 0
        last_active = state["last_active_date"] if state else None
        total_blocks = state["total_blocks_completed"] if state else 0
        total_mins = state["total_minutes_completed"] if state else 0

        # Calculate effective streak
        effective_streak = 0
        is_streak_broken = False
        completed_today = False
        in_grace_period = False

        if last_active is not None:
            last_date = datetime.strptime(last_active, "%Y-%m-%d").date()
            delta_days = (today_date - last_date).days

            if delta_days == 0:
                effective_streak = curr_streak
                completed_today = True
            elif delta_days == 1:
                # Active yesterday, pending today
                effective_streak = curr_streak
                completed_today = False
            elif delta_days == 2 and is_night_owl:
                # Late-night grace window (00:00 - 04:00 AM)
                effective_streak = curr_streak
                completed_today = False
                in_grace_period = True
            else:
                # Missed 1+ days -> streak is broken, shows 0
                effective_streak = 0
                is_streak_broken = True
                completed_today = False

        # Get today's stats
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(duration_mins), 0) FROM daily_logs WHERE date = ?",
            (today_str,),
        )
        today_row = cursor.fetchone()
        today_blocks = today_row[0]
        today_mins = today_row[1]

        # Check weekly streak freeze status
        monday = today_date - timedelta(days=today_date.weekday())
        sunday = monday + timedelta(days=6)
        cursor.execute(
            "SELECT COUNT(*), MAX(date) FROM streak_freezes WHERE date >= ? AND date <= ?",
            (monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")),
        )
        freeze_info = cursor.fetchone()
        freeze_used_this_week = (freeze_info[0] > 0) if freeze_info else False
        last_freeze_date = freeze_info[1] if freeze_info else None

        return {
            "today_date": today_str,
            "today_blocks": today_blocks,
            "today_minutes": today_mins,
            "current_streak": effective_streak,
            "stored_streak": curr_streak,
            "longest_streak": long_streak,
            "last_active_date": last_active,
            "completed_today": completed_today,
            "is_streak_broken": is_streak_broken,
            "in_grace_period": in_grace_period,
            "freeze_used_this_week": freeze_used_this_week,
            "last_freeze_date": last_freeze_date,
            "total_blocks_completed": total_blocks,
            "total_minutes_completed": total_mins,
        }


def get_history(
    days: int = 7,
    tz_name: str = DEFAULT_TIMEZONE,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Fetches completed blocks summary and topics for the last N calendar days."""
    today_str = get_today_date(tz_name)
    today_date = datetime.strptime(today_str, "%Y-%m-%d").date()
    start_date = (today_date - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date, COUNT(*) as blocks, COALESCE(SUM(duration_mins), 0) as total_mins,
                   GROUP_CONCAT(DISTINCT topic) as topics
            FROM daily_logs
            WHERE date >= ?
            GROUP BY date
            ORDER BY date DESC
            """,
            (start_date,),
        )
        rows = cursor.fetchall()

        history_map = {
            row["date"]: {
                "blocks": row["blocks"],
                "total_mins": row["total_mins"],
                "topics": row["topics"] if row["topics"] else "",
            }
            for row in rows
        }

        # Build full sequence of days (including 0-block days)
        result = []
        for i in range(days):
            d_str = (today_date - timedelta(days=i)).strftime("%Y-%m-%d")
            data = history_map.get(d_str, {"blocks": 0, "total_mins": 0, "topics": ""})
            result.append({
                "date": d_str,
                "blocks": data["blocks"],
                "total_mins": data["total_mins"],
                "topics": data["topics"],
            })

        return result


def apply_streak_freeze(
    reason: str = "Rest day",
    tz_name: str = DEFAULT_TIMEZONE,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Applies a streak freeze / rest day for the current calendar week (Monday to Sunday).
    Only 1 rest day is permitted per week.
    Returns success status, message, and freeze details.
    """
    tz = pytz.timezone(tz_name)
    now_dt = datetime.now(tz)
    today_date = now_dt.date()
    today_str = today_date.strftime("%Y-%m-%d")

    # Calendar week runs Monday to Sunday
    monday = today_date - timedelta(days=today_date.weekday())
    sunday = monday + timedelta(days=6)
    monday_str = monday.strftime("%Y-%m-%d")
    sunday_str = sunday.strftime("%Y-%m-%d")

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Check if already used this week
        cursor.execute(
            """
            SELECT date, reason, created_at
            FROM streak_freezes
            WHERE date >= ? AND date <= ?
            """,
            (monday_str, sunday_str),
        )
        existing = cursor.fetchone()
        if existing:
            return {
                "ok": False,
                "already_used": True,
                "used_date": existing["date"],
                "reason": existing["reason"],
                "message": f"You've already used your 1 Rest Day for this week on {existing['date']}. Rest days reset every Monday!",
            }

        # Insert freeze
        cursor.execute(
            "INSERT INTO streak_freezes (date, reason) VALUES (?, ?)",
            (today_str, reason),
        )

        # Update streak_state: protect current streak by updating last_active_date to today_str
        cursor.execute(
            """
            SELECT current_streak, longest_streak, last_active_date
            FROM streak_state WHERE id = 1
            """
        )
        state = cursor.fetchone()
        curr_streak = state["current_streak"] if state else 0
        long_streak = state["longest_streak"] if state else 0

        cursor.execute(
            """
            UPDATE streak_state
            SET last_active_date = ?
            WHERE id = 1
            """,
            (today_str,),
        )
        conn.commit()

        return {
            "ok": True,
            "already_used": False,
            "date": today_str,
            "reason": reason,
            "current_streak": curr_streak,
            "message": f"Rest day credited for {today_str}. Streak of {curr_streak} day(s) protected!",
        }


def get_weekly_summary(
    tz_name: str = DEFAULT_TIMEZONE,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Returns weekly deep work summary (Monday through Sunday),
    including total hours, blocks, topics covered, and consistency rating.
    """
    tz = pytz.timezone(tz_name)
    now_dt = datetime.now(tz)
    today_date = now_dt.date()
    monday = today_date - timedelta(days=today_date.weekday())
    sunday = monday + timedelta(days=6)
    monday_str = monday.strftime("%Y-%m-%d")
    sunday_str = sunday.strftime("%Y-%m-%d")

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date, duration_mins, topic
            FROM daily_logs
            WHERE date >= ? AND date <= ?
            ORDER BY date ASC
            """,
            (monday_str, sunday_str),
        )
        rows = cursor.fetchall()

        total_mins = sum(r["duration_mins"] for r in rows)
        total_blocks = len(rows)
        active_days = len(set(r["date"] for r in rows))

        cursor.execute(
            "SELECT COUNT(*), MAX(date) FROM streak_freezes WHERE date >= ? AND date <= ?",
            (monday_str, sunday_str),
        )
        freeze_row = cursor.fetchone()
        freezes_used = freeze_row[0] if freeze_row else 0
        last_freeze_date = freeze_row[1] if freeze_row else None

        # Collect unique topics
        raw_topics = [r["topic"] for r in rows if r["topic"]]
        unique_topics = []
        for t in raw_topics:
            if t not in unique_topics:
                unique_topics.append(t)

        consistency_days = active_days + freezes_used
        consistency_pct = int((min(7, consistency_days) / 7.0) * 100)

        return {
            "week_start": monday_str,
            "week_end": sunday_str,
            "total_mins": total_mins,
            "total_hours": round(total_mins / 60.0, 1),
            "total_blocks": total_blocks,
            "active_days": active_days,
            "freezes_used": freezes_used,
            "last_freeze_date": last_freeze_date,
            "consistency_pct": consistency_pct,
            "topics": unique_topics,
        }


def get_breaks(
    limit: int = 10,
    db_path: str = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Fetches recent streak break events."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, broken_on_date, lost_streak_count, recorded_at, notes
            FROM streak_break_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r["id"],
                "broken_on_date": r["broken_on_date"],
                "lost_streak_count": r["lost_streak_count"],
                "recorded_at": r["recorded_at"],
                "notes": r["notes"],
            }
            for r in rows
        ]


def check_db_health(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Tests SQLite read and write capability for diagnostic checks."""
    try:
        init_db(db_path)
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM daily_logs")
            daily_logs_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM streak_break_log")
            breaks_count = cursor.fetchone()[0]

            cursor.execute("SELECT current_streak, longest_streak FROM streak_state WHERE id = 1")
            streak_info = cursor.fetchone()

            return {
                "ok": True,
                "db_path": db_path,
                "daily_logs_count": daily_logs_count,
                "breaks_count": breaks_count,
                "current_streak": streak_info["current_streak"] if streak_info else 0,
                "longest_streak": streak_info["longest_streak"] if streak_info else 0,
                "error": None,
            }
    except Exception as e:
        return {
            "ok": False,
            "db_path": db_path,
            "error": str(e),
        }
