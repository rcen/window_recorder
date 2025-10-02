# Microsoft Teams Tracking Issue

## Problem Description
Microsoft Teams tracking is unreliable - it takes a while to display tracking info, and sometimes it just misses the activity entirely.

## Root Cause Analysis

### Discovery (Oct 2, 2025)
Investigation revealed that **Microsoft Teams runs as a Progressive Web App (PWA) inside Microsoft Edge**, not as a standalone application:

```
Window Title: "Microsoft Teams - Chat | OCRT Core Tech Standup | Microsoft Teams"
Process: msedge.exe
Window Class: Chrome_WidgetWin_1
Executable: C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
```

### Why This Causes Problems

1. **Process-Based Detection Fails**
   - Traditional window tracking looks for `teams.exe` or similar process names
   - Teams actually runs as `msedge.exe`, which hosts many different web apps
   - Cannot distinguish Teams from other Edge windows by process name alone

2. **Window Title Retrieval Issues**
   - `GetWindowText()` on Chromium/Edge PWA windows can return empty strings
   - Window titles may take time to update when switching contexts within Teams
   - The Electron/Chromium architecture causes delays in title propagation

3. **Dynamic Title Structure**
   - Teams uses complex, multi-part titles: "Microsoft Teams - [Section] | [Detail] | Microsoft Teams"
   - Titles change frequently as you navigate (Chat → Calendar → Calls)
   - Makes consistent tracking difficult

## Implemented Workarounds

### 1. Retry Logic (Lines ~690-710)
```python
for attempt in range(3):
    try:
        window_name = win32gui.GetWindowText(parent)
        if window_name:
            break
        if attempt < 2:
            time.sleep(0.05)  # 50ms delay before retry
    except:
        if attempt < 2:
            time.sleep(0.05)
        continue
```
- Attempts up to 3 times to get window title
- Handles slow-responding Chromium windows
- Max overhead: 150ms (only when needed)

### 2. Error Handling Improvement (Lines ~742-744)
```python
if last_window and last_window != 'start tracking':
    return last_window, last_window_url
return "desktop", None
```
- Returns last known window instead of "desktop" on errors
- Maintains tracking continuity during temporary glitches

### 3. Teams-Specific Title Normalization (Lines ~719-729)
```python
if 'microsoft teams' in normalized_title or 'teams.microsoft.com' in normalized_title:
    logging.debug(f"Teams detected via title - Window: '{window_name}', Process: {process_name}")
    if process_name == 'msedge.exe' or process_name == 'chrome.exe':
        if '|' in window_name:
            parts = [p.strip() for p in window_name.split('|')]
            normalized_title = f"microsoft teams - {parts[1] if len(parts) > 1 else 'active'}".lower()
        else:
            normalized_title = "microsoft teams"
```
- Detects Teams by window title pattern
- Extracts specific context (Chat, Calendar, Meeting name)
- Normalizes to consistent format for database storage

### 4. Performance Improvements
- Main loop sleep: `0.5s` → `0.3s` (200ms faster)
- Mouse idle check: removed `0.1s` sleep (100ms faster)
- **Net improvement: ~300ms faster response time**

## Current Limitations

Despite the workarounds, Teams tracking remains **partially unreliable** due to fundamental architectural issues:

1. **Still depends on `GetWindowText()`** which is not designed for Chromium-based apps
2. **Cannot distinguish Teams from other Edge tabs/PWAs** running in the same process
3. **Title updates still lag** behind actual UI state changes

## Future Improvements (TODO)

### Option 1: UI Automation API
```python
import uiautomation as auto
control = auto.GetFocusedControl()
# Can access deeper properties than GetWindowText()
```
- More reliable for modern apps
- Can access ARIA labels, accessibility properties
- Higher overhead but better accuracy

### Option 2: Accessibility APIs
```python
from pywinauto import Application
app = Application(backend="uia").connect(process=pid)
# Use UI Automation backend instead of Win32
```
- Designed for Electron/Chromium apps
- Better support for PWAs
- Already partially imported (lines 66-67)

### Option 3: Teams API Integration
- Use Microsoft Graph API to query actual Teams activity
- Requires authentication and API permissions
- Most accurate but complex to implement

### Option 4: Browser Extension
- Create Edge/Chrome extension that reports Teams activity
- Direct access to Teams web app state
- Requires separate extension installation

## Testing & Validation

To test Teams tracking after changes:

1. Run the script: `python script.py`
2. Use Microsoft Teams for 5-10 minutes
3. Check debug log for Teams detection:
   ```powershell
   Select-String -Path "debug.log" -Pattern "Teams" -Context 0,2 | Select-Object -Last 20
   ```
4. Generate analytics: `python analytics.py`
5. Verify Teams activity appears in HTML timeline

## Configuration

Teams is configured in `config.dat`:
```
microsoft teams: mail
```

This maps Teams activity to the "mail" category for analytics reporting.

## References
- [GetWindowText() documentation](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowtext)
- [Chromium PWA architecture](https://web.dev/progressive-web-apps/)
- [UI Automation API](https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32)

---
**Last Updated:** October 2, 2025  
**Status:** Workaround implemented, but fundamental issue remains
