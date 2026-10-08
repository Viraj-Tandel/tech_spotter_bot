Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\user\.gemini\antigravity\scratch\tech-spotter-bot"
WshShell.Run """C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"" bot.py", 0, False
