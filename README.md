# Tech Spotter (Digital Body Double & Consistency Engine)

A targeted Telegram bot designed to eliminate study procrastination on **Namaste DSA** and side projects through time-boxing, body doubling, and zero-overhead streak tracking.

---

## 🚀 Key Features

* **Focused Study Blocks (`/block`, `/block1`, `/block2`)**: Time-boxed countdown sessions (default 30 min) powered by `python-telegram-bot`'s asynchronous `JobQueue`.
* **Slack Shield Protection (`/block2`)**: Automatically enforces keeping Slack, Teams, and Outlook closed during the office morning focus window (10:30 – 11:00 AM).
* **Automated Daily Nudges**:
  * **09:45 AM IST**: Morning check-in for Block 1 (Theory / Namaste DSA).
  * **10:30 AM IST**: Office arrival check-in for Block 2 (Code / Slack Shield).
  * **10:00 PM IST**: Gentle sleep reminder ensuring 7 hours of rest for 06:00 AM gym.
* **Zero-Overhead Streak Tracking**:
  * Completing **1 block per day** preserves and increments the streak.
  * Same-day additional blocks count as "Bonus Reps" without artificially inflating streak days.
  * Premature aborts (`/stop`) discard the session completely (no fake streak padding).
  * Missed days dynamically reset `/status` to `0` and record an entry in `streak_break_log`.
* **Health & Diagnostics (`/health` or `/ping`)**: Live test command verifying bot responsiveness, database read/write connectivity, and active timers.
* **Single-User Whitelist Security**: Ignores unauthorized users silently.

---

## 🛠️ Bot Commands

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/start` | None | Welcome message, user authentication check, and usage instructions. |
| `/block` | `[minutes]` (default: 30) | Starts a focus block. Auto-increments today's block count. |
| `/block1` | None | Explicit shortcut for Block 1 (Theory / Morning Home Session). |
| `/block2` | None | Explicit shortcut for Block 2 (Code / Office Desk with Slack Shield). |
| `/stop` | None | Cancels ongoing timer prematurely (completely discarded). |
| `/status` | None | Shows live countdown, today's blocks, dynamic streak, and best streak. |
| `/history` | None | Shows past 7 days of completed blocks and deep work minutes. |
| `/breaks` | None | Shows the audit log of broken streaks and lost days. |
| `/health` or `/ping` | None | Diagnostic command checking bot uptime and database connectivity. |

---

## ⚙️ Setup & Configuration

### 1. Configure `.env`
Create a `.env` file in the project root (copied from `.env.example`):

```bash
# 1. Get TELEGRAM_BOT_TOKEN from @BotFather on Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# 2. Get TELEGRAM_USER_ID from @userinfobot on Telegram (numerical ID)
TELEGRAM_USER_ID=123456789

# Optional: Timezone configuration (defaults to Asia/Kolkata)
TIMEZONE=Asia/Kolkata
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the Bot Locally
You can run the bot in any of these ways:

* **Option A (Visible Console):** Double-click [`start_bot.bat`](file:///c:/Users/user/.gemini/antigravity/scratch/tech-spotter-bot/start_bot.bat)
* **Option B (Silent Background):** Double-click [`start_silent.vbs`](file:///c:/Users/user/.gemini/antigravity/scratch/tech-spotter-bot/start_silent.vbs) *(runs completely hidden without a terminal window)*
* **Option C (To Stop Silent Bot):** Double-click [`stop_bot.bat`](file:///c:/Users/user/.gemini/antigravity/scratch/tech-spotter-bot/stop_bot.bat)
* **Option D (Command line):**
  ```powershell
  python bot.py
  ```

### 4. Run the Test Suite
```powershell
pytest test_spotter.py -v
```

---

## 📦 Background Daemon (PM2 on Laptop)
If you want the bot to automatically restart if it closes or whenever your laptop starts:
```powershell
npm install -g pm2
pm2 start bot.py --name "spotter-bot" --interpreter python
pm2 save
```
