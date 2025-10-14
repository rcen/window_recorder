# Habit Calendar Troubleshooting Guide

## Problem: Checkboxes revert immediately after clicking

### Solution: Start the habit server BEFORE opening the HTML page

The habit calendar needs a local server running to save your checkbox clicks to the database.

## Quick Start

### Step 1: Start the Habit Server
**Windows:**
```bash
start_habit_server.bat
```

**Manual start:**
```bash
C:\projects\window_recorder\winrecord_env\Scripts\python.exe habit_server.py
```

You should see:
```
Habit tracker server running at http://127.0.0.1:8042/habits
```

### Step 2: Verify Server is Running
**Windows PowerShell:**
```powershell
netstat -an | Select-String "8042"
```

You should see:
```
TCP    127.0.0.1:8042         0.0.0.0:0              LISTENING
```

### Step 3: Open the HTML Report
Now open `html/index.html` in your browser. The checkboxes should work!

## Testing the Server Directly

Test if the server responds correctly:

**PowerShell:**
```powershell
$body = @{habit='Test';date='2025-10-14';completed=$true} | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8042/habits' -Method POST -Body $body -ContentType 'application/json'
```

**Expected response:**
```
status     : ok
habit      : Test
date       : 2025-10-14
completed  : True
updated_at : 2025-10-14T13:49:49.486489-04:00
```

## How It Works

1. **Click checkbox** → JavaScript detects the change
2. **Mark as pending** → Prevents race conditions with auto-sync
3. **POST to server** → `http://127.0.0.1:8042/habits` with habit/date/completed
4. **Server saves** → Writes to `activity.db` with timestamp
5. **Response received** → Updates the "Updated HH:MM" badge
6. **Streak recalculated** → Counter updates (e.g., 0d → 1d → 2d)

## Common Issues

### Issue 1: "Could not reach habit server" message
**Cause:** Server not running
**Fix:** Start `habit_server.py` before opening HTML

### Issue 2: Checkbox reverts after clicking
**Cause:** Server not running or crashed
**Fix:** 
1. Check if server is running: `netstat -an | Select-String "8042"`
2. If not, start it: `start_habit_server.bat`
3. Refresh the browser page (Ctrl+R or F5)

### Issue 3: Streak counter doesn't update
**Cause:** JavaScript error or stale page
**Fix:**
1. Open browser console (F12)
2. Look for errors (should see `[habit-server]` logs if working)
3. Hard refresh: Ctrl+Shift+R or Ctrl+F5
4. Re-run analytics.py to regenerate HTML

### Issue 4: Changes don't persist after closing browser
**Cause:** This is expected! The server writes to database immediately
**Verify:** 
```python
python -c "import database; database.initialize_database(); print(database.get_habit_completions(['Exercise'], '2025-10-14', '2025-10-14'))"
```

## Debug Mode

Check what the server is logging:

1. Stop the background server
2. Run manually in a visible window:
   ```bash
   C:\projects\window_recorder\winrecord_env\Scripts\python.exe habit_server.py
   ```
3. Click checkboxes in the browser
4. Watch the console for `[habit-server]` logs

## Browser Console

Open your browser's developer tools (F12) and check the Console tab for:
- ✅ Success: `Saved Exercise for 2025-10-14.`
- ❌ Error: `Habit update failed` or `Could not reach habit server`

## Workflow Summary

```
1. Configure habits in config.py
2. Run: analytics.py (generates HTML with calendar)
3. Start: habit_server.py (enables checkbox persistence)
4. Open: html/index.html (interact with calendar)
5. Click: Checkboxes stay checked! ✓
6. Counter: Increments (0d → 1d → 2d...) ✓
7. Badge: Shows "Updated HH:MM" ✓
```

## Still Not Working?

1. Ensure Python environment is activated
2. Verify database exists: ````bash
# Check if database exists
ls data/activity.sqlite

# Check database contents`
3. Check config.py has HABITS defined
4. Regenerate HTML: `python analytics.py`
5. Restart habit server
6. Clear browser cache and hard refresh
7. Check firewall isn't blocking localhost:8042

## Need Help?

Check the browser console (F12) and server terminal output for error messages.
