"""
test_spotter.py - Comprehensive test suite for Tech Spotter Bot.
Tests SQLite database operations, streak logic, break audit trail, dynamic status, and bot components.
"""

import os
import tempfile
import pytest
from datetime import datetime, timedelta
import pytz

import database


@pytest.fixture
def test_db():
    """Provides a fresh temporary SQLite database path for each test."""
    temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_fd)
    database.init_db(temp_path)
    yield temp_path
    if os.path.exists(temp_path):
        os.remove(temp_path)


def test_init_db(test_db):
    """Verifies schema initialization and singleton streak state row."""
    health = database.check_db_health(test_db)
    assert health["ok"] is True
    assert health["daily_logs_count"] == 0
    assert health["breaks_count"] == 0
    assert health["current_streak"] == 0
    assert health["longest_streak"] == 0


def test_single_block_starts_streak(test_db):
    """
    Test Day 1: Completing a single block starts the streak at 1.
    Per user clarification: completing 1 block is sufficient to count a streak.
    """
    result = database.record_completed_block(30, db_path=test_db)
    assert result["block_number"] == 1
    assert result["duration_mins"] == 30
    assert result["today_blocks"] == 1
    assert result["today_minutes"] == 30
    assert result["current_streak"] == 1
    assert result["longest_streak"] == 1
    assert result["streak_broken"] is False


def test_second_block_same_day(test_db):
    """
    Test Day 1: Completing a second block on the same day increments today's blocks,
    but keeps the streak count at 1.
    """
    database.record_completed_block(30, db_path=test_db)
    result = database.record_completed_block(30, db_path=test_db)

    assert result["block_number"] == 2
    assert result["today_blocks"] == 2
    assert result["today_minutes"] == 60
    assert result["current_streak"] == 1
    assert result["longest_streak"] == 1


def test_consecutive_day_increments_streak(test_db):
    """
    Simulate Day 1 and Day 2 consecutive completion:
    Streak should increment to 2.
    """
    # Seed Day 1
    yesterday = (datetime.now(pytz.timezone("Asia/Kolkata")) - timedelta(days=1)).strftime("%Y-%m-%d")
    with database.get_db_connection(test_db) as conn:
        conn.execute(
            """
            UPDATE streak_state
            SET current_streak = 1, longest_streak = 1, last_active_date = ?,
                total_blocks_completed = 1, total_minutes_completed = 30
            WHERE id = 1
            """,
            (yesterday,),
        )
        conn.commit()

    # Complete block today (Day 2)
    result = database.record_completed_block(30, db_path=test_db)
    assert result["current_streak"] == 2
    assert result["longest_streak"] == 2
    assert result["streak_broken"] is False


def test_broken_streak_records_audit_log_and_resets(test_db):
    """
    Simulate user who had a 7-day streak, missed Day 8, and completes a block on Day 9.
    Should record audit break log with lost_streak_count = 7, and reset current_streak to 1.
    """
    two_days_ago = (datetime.now(pytz.timezone("Asia/Kolkata")) - timedelta(days=2)).strftime("%Y-%m-%d")
    with database.get_db_connection(test_db) as conn:
        conn.execute(
            """
            UPDATE streak_state
            SET current_streak = 7, longest_streak = 7, last_active_date = ?,
                total_blocks_completed = 10, total_minutes_completed = 300
            WHERE id = 1
            """,
            (two_days_ago,),
        )
        conn.commit()

    result = database.record_completed_block(30, db_path=test_db)
    assert result["streak_broken"] is True
    assert result["lost_streak_count"] == 7
    assert result["current_streak"] == 1
    assert result["longest_streak"] == 7  # Longest preserved

    # Check break log
    breaks = database.get_breaks(limit=5, db_path=test_db)
    assert len(breaks) == 1
    assert breaks[0]["lost_streak_count"] == 7


def test_status_dynamically_shows_zero_if_missed_day(test_db):
    """
    User clarification test:
    'Curent strak lets say I have done consitenly for 7 days and 8th day i missed so it is break and on 9th day it should show 0'
    When user has not yet completed a block today and 2+ days elapsed since last block,
    /status should dynamically report current_streak as 0 and broken as True.
    """
    two_days_ago = (datetime.now(pytz.timezone("Asia/Kolkata")) - timedelta(days=2)).strftime("%Y-%m-%d")
    with database.get_db_connection(test_db) as conn:
        conn.execute(
            """
            UPDATE streak_state
            SET current_streak = 7, longest_streak = 7, last_active_date = ?,
                total_blocks_completed = 10, total_minutes_completed = 300
            WHERE id = 1
            """,
            (two_days_ago,),
        )
        conn.commit()

    status = database.get_status(db_path=test_db)
    assert status["current_streak"] == 0
    assert status["is_streak_broken"] is True
    assert status["stored_streak"] == 7
    assert status["longest_streak"] == 7
    assert status["completed_today"] is False


def test_status_pending_today(test_db):
    """
    If active yesterday and today is pending (no block yet),
    effective streak should still show current streak (not broken yet).
    """
    yesterday = (datetime.now(pytz.timezone("Asia/Kolkata")) - timedelta(days=1)).strftime("%Y-%m-%d")
    with database.get_db_connection(test_db) as conn:
        conn.execute(
            """
            UPDATE streak_state
            SET current_streak = 4, longest_streak = 4, last_active_date = ?,
                total_blocks_completed = 6, total_minutes_completed = 180
            WHERE id = 1
            """,
            (yesterday,),
        )
        conn.commit()

    status = database.get_status(db_path=test_db)
    assert status["current_streak"] == 4
    assert status["is_streak_broken"] is False
    assert status["completed_today"] is False


def test_history_aggregation(test_db):
    """Verifies 7 days history returns 7 rows including empty days."""
    database.record_completed_block(30, db_path=test_db)
    database.record_completed_block(45, db_path=test_db)

    history = database.get_history(days=7, db_path=test_db)
    assert len(history) == 7
    # First row is today
    assert history[0]["blocks"] == 2
    assert history[0]["total_mins"] == 75
    # Earlier days have 0 blocks
    assert history[1]["blocks"] == 0
    assert history[1]["total_mins"] == 0


def test_health_check(test_db):
    """Tests database health check output."""
    health = database.check_db_health(test_db)
    assert health["ok"] is True
    assert "spotter" in health["db_path"] or ".db" in health["db_path"]
    assert health["daily_logs_count"] == 0
    assert health["breaks_count"] == 0


# -------------------------------------------------------------
# Bot Handler and Security Tests
# -------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock
import bot


@pytest.mark.anyio
async def test_bot_auth_gatekeeper(monkeypatch):
    """Verifies unauthorized user messages are silently dropped."""
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 12345)

    # Unauthorized user
    unauth_update = MagicMock()
    unauth_update.effective_user.id = 99999
    unauth_update.message.reply_text = AsyncMock()
    context = MagicMock()

    await bot.cmd_start(unauth_update, context)
    unauth_update.message.reply_text.assert_not_called()

    # Authorized user
    auth_update = MagicMock()
    auth_update.effective_user.id = 12345
    auth_update.message.reply_text = AsyncMock()

    await bot.cmd_start(auth_update, context)
    auth_update.message.reply_text.assert_called_once()
    assert "Welcome to Tech Spotter" in auth_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_bot_health_command(monkeypatch, test_db):
    """Verifies /health command checks database and reports status."""
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 12345)
    monkeypatch.setattr(bot, "DB_PATH", test_db)

    update = MagicMock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await bot.cmd_health(update, context)
    update.message.reply_text.assert_called_once()
    reply_msg = update.message.reply_text.call_args[0][0]
    assert "Tech Spotter Health & Diagnostics" in reply_msg
    assert "Online & Responding" in reply_msg
    assert "Connected" in reply_msg


@pytest.mark.anyio
async def test_bot_stop_command_discards_block(monkeypatch, test_db):
    """
    Tests /stop command when timer is active:
    Cancels job, clears active_timer, leaves daily_logs with 0 records.
    """
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 12345)
    monkeypatch.setattr(bot, "DB_PATH", test_db)

    mock_job = MagicMock()
    bot.active_timers[12345] = {
        "job": mock_job,
        "block_number": 1,
        "duration_mins": 30,
        "start_time": datetime.now(),
        "end_time": datetime.now() + timedelta(minutes=30),
        "session_type": "block1",
    }

    update = MagicMock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await bot.cmd_stop(update, context)

    # Job removed and active_timers cleared
    mock_job.schedule_removal.assert_called_once()
    assert 12345 not in bot.active_timers
    assert "cancelled" in update.message.reply_text.call_args[0][0]

    # Verify nothing was written to daily_logs
    health = database.check_db_health(test_db)
    assert health["daily_logs_count"] == 0


@pytest.mark.anyio
async def test_active_timer_guard(monkeypatch, test_db):
    """Verifies starting another block while one is running is blocked with a warning."""
    monkeypatch.setattr(bot, "AUTHORIZED_USER_ID", 12345)
    monkeypatch.setattr(bot, "DB_PATH", test_db)

    now = datetime.now(bot.TIMEZONE)
    bot.active_timers[12345] = {
        "job": MagicMock(),
        "block_number": 1,
        "duration_mins": 30,
        "start_time": now,
        "end_time": now + timedelta(minutes=25),
        "session_type": "block1",
    }

    update = MagicMock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    # Try starting block 2 while block 1 is active
    await bot.cmd_block2(update, context)
    update.message.reply_text.assert_called_once()
    assert "Active block already in progress" in update.message.reply_text.call_args[0][0]

    # Clean up
    bot.active_timers.clear()
