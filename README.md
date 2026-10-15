# Tech Spotter (Digital Body Double & Consistency Engine)

A targeted Telegram bot designed to eliminate study procrastination on **Namaste DSA** and side projects through time-boxing, body doubling, and zero-overhead streak tracking.

---

## 🚀 Key Features

* **Interactive One-Tap Action Buttons**: Full inline keyboard on Telegram (`⏱️ 15m`, `⏱️ 30m`, `⏱️ 45m`, `⏱️ 60m`, `📊 Status`, `🧊 Rest Day`) for zero-friction mobile interaction.
* **Focused Study Blocks (`/block`, `/block1`, `/block2`)**: Time-boxed countdown sessions (15, 30, 45, 60m) powered by `python-telegram-bot`'s asynchronous `JobQueue`.
* **Topic Tagging**: Attach study topics (e.g. `/block 15 Trees` or `/block 30 Binary Search`) to track learning progression in *Namaste DSA*.
* **Late-Night Session Protection & Night-Owl Grace**:
  * Blocks started late at night (e.g. 11:45 PM) are credited to the day they started, even if the timer completes after midnight.
  * Late-night sessions between 12:00 AM and 04:00 AM automatically attribute to yesterday if yesterday had no blocks, protecting your streak before sleeping.
* **Weekly Rest Day / Streak Freeze (`/freeze` or `/rest`)**: 1 protected rest day per calendar week for gym recovery or corporate releases without breaking your streak.
* **Sunday Night Weekly Recap (`/weekly`)**: Automated digest every Sunday at 08:00 PM with total deep work hours, consistency %, and topics covered.
* **Gentle Sleep Reminder**: Daily 10:00 PM reminder ensuring 7 hours of rest for 06:00 AM gym.
* **Zero-Overhead Streak Tracking**: Any block $\ge$ 15 minutes increments and locks in the streak.
* **Single-User Whitelist Security**: Ignores unauthorized users silently.

---

## 🛠️ Bot Commands

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/start` or `/help` | None | Welcome message with interactive action buttons and usage instructions. |
| `/block` | `[mins] [topic]` | Starts a focus block (e.g., `/block 15 Trees` or `/block 45`). |
| `/block1` | `[topic]` | Shortcut for Block 1 (Namaste DSA Theory, default 30 mins). |
| `/block2` | `[topic]` | Shortcut for Block 2 (Namaste DSA Hands-on Code + Slack Shield). |
| `/stop` | None | Cancels ongoing timer prematurely (completely discarded). |
| `/status` | None | Live countdown, today's blocks, dynamic streak, and rest day status. |
| `/history` | None | Past 7 days breakdown with completed blocks and topics studied. |
| `/weekly` or `/summary` | None | Full current week's deep work summary, hours, and consistency grade. |
| `/freeze` or `/rest` | `[reason]` | Uses your 1 weekly rest day to protect your streak. |
| `/breaks` | None | Audit log of broken streaks and lost days. |
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
