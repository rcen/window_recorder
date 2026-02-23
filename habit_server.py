"""Simple local HTTP server to record and retrieve habit completions."""
from __future__ import annotations

import json
import datetime
import sys
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Redirect stdout/stderr to devnull if running without a console (pythonw.exe)
if sys.stdout is None or not hasattr(sys.stdout, 'write'):
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None or not hasattr(sys.stderr, 'write'):
    sys.stderr = open(os.devnull, 'w')

import database
from config import TIMEZONE, HABITS
from productivity_agent import ProductivityAgent
import pytz

HOST = '127.0.0.1'
PORT = 8042

# Global productivity agent instance for the server
_productivity_agent = None

def get_productivity_agent():
    """Get or create the productivity agent instance."""
    global _productivity_agent
    if _productivity_agent is None:
        _productivity_agent = ProductivityAgent()
    return _productivity_agent


def _default_start_end(days: int = 30) -> tuple[str, str]:
    tz = datetime.timezone.utc
    today = datetime.datetime.now(tz).astimezone().date()
    start = today - datetime.timedelta(days=days - 1)
    return start.isoformat(), today.isoformat()


class HabitRequestHandler(BaseHTTPRequestHandler):
    server_version = 'HabitTracker/1.0'

    def _set_headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _handle_productivity_get(self) -> None:
        """Handle GET /productivity - returns current productivity status."""
        try:
            agent = get_productivity_agent()
            data = agent.get_dashboard_data()
            self._set_headers(200)
            self.wfile.write(json.dumps(data).encode('utf-8'))
        except Exception as e:
            print(f"[habit-server] Error in /productivity: {e}")
            self._set_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

    def _handle_goals_get(self) -> None:
        """Handle GET /productivity/goals - returns goal configurations."""
        try:
            agent = get_productivity_agent()
            goals_data = {
                'goals': [
                    {
                        'category': g.category,
                        'target_minutes': g.daily_target_minutes,
                        'warning_threshold': g.warning_threshold,
                        'critical_threshold': g.critical_threshold,
                        'is_positive': g.is_positive,
                        'enabled': g.enabled
                    }
                    for g in agent.goals.values()
                ]
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(goals_data).encode('utf-8'))
        except Exception as e:
            print(f"[habit-server] Error in /productivity/goals: {e}")
            self._set_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Reduce noise by logging to stdout once per request
        print("[habit-server]" , self.address_string(), format % args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        
        # Serve index.html for root path
        if parsed.path == '/' or parsed.path == '':
            try:
                with open('html/index.html', 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
                return
            except FileNotFoundError:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'index.html not found'}).encode('utf-8'))
                return
        
        # Handle productivity endpoints
        if parsed.path == '/productivity':
            self._handle_productivity_get()
            return
        elif parsed.path == '/productivity/goals':
            self._handle_goals_get()
            return

        # Handle must_done status queries
        if parsed.path == '/must_done/status':
            params = parse_qs(parsed.query)
            week_id = params.get('week_id', [None])[0]
            if not week_id:
                self._set_headers(400)
                self.wfile.write(json.dumps({'error': 'Missing week_id'}).encode('utf-8'))
                return

            import sqlite3
            try:
                conn = sqlite3.connect('data/activity.sqlite')
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT task_id, completed, completed_at FROM must_done_items WHERE week_id = ?',
                    (week_id,),
                )
                rows = cursor.fetchall()
                conn.close()
                items = {
                    str(task_id): {
                        'completed': bool(completed),
                        'completed_at': completed_at,
                    }
                    for task_id, completed, completed_at in rows
                }
                self._set_headers(200)
                self.wfile.write(
                    json.dumps({'status': 'success', 'week_id': week_id, 'items': items}).encode('utf-8')
                )
                return
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return

        # Handle must_be_done list (ad-hoc todos)
        if parsed.path == '/must_be_done/list':
            params = parse_qs(parsed.query)
            week_id = params.get('week_id', [None])[0]
            month_id = params.get('month_id', [None])[0]
            today_id = params.get('today_id', [None])[0]
            include_persistent = params.get('include_persistent', ['1'])[0] != '0'
            include_completed = params.get('include_completed', ['1'])[0] != '0'
            include_expired = params.get('include_expired', ['1'])[0] != '0'
            try:
                weeks_back = int(params.get('weeks_back', ['12'])[0])
            except Exception:
                weeks_back = 12
            try:
                months_back = int(params.get('months_back', ['6'])[0])
            except Exception:
                months_back = 6
            try:
                days_back = int(params.get('days_back', ['7'])[0])
            except Exception:
                days_back = 7

            weeks_back = max(1, min(104, weeks_back))
            months_back = max(1, min(36, months_back))
            days_back = max(1, min(30, days_back))

            def _week_ids_for_range(current_week_id: str, count: int) -> list[str]:
                try:
                    base = datetime.date.fromisoformat(current_week_id)
                except Exception:
                    return [current_week_id]
                return [(base - datetime.timedelta(days=7 * i)).isoformat() for i in range(count)]

            def _day_ids_for_range(current_day_id: str, count: int) -> list[str]:
                try:
                    base = datetime.date.fromisoformat(current_day_id)
                except Exception:
                    return [current_day_id]
                return [(base - datetime.timedelta(days=i)).isoformat() for i in range(count)]

            def _month_ids_for_range(current_month_id: str, count: int) -> list[str]:
                try:
                    year_str, month_str = current_month_id.split('-', 1)
                    year = int(year_str)
                    month = int(month_str)
                    if not (1 <= month <= 12):
                        raise ValueError('bad month')
                except Exception:
                    return [current_month_id]

                result: list[str] = []
                y, m = year, month
                for _ in range(count):
                    result.append(f"{y:04d}-{m:02d}")
                    m -= 1
                    if m == 0:
                        m = 12
                        y -= 1
                return result

            try:
                items: list[dict] = []

                if today_id:
                    day_ids = [today_id] if not include_expired else _day_ids_for_range(today_id, days_back)
                    items.extend(
                        database.get_must_be_done_items_multi(
                            bucket_type='today',
                            bucket_ids=day_ids,
                            include_completed=include_completed,
                        )
                    )

                if week_id:
                    week_ids = [week_id] if not include_expired else _week_ids_for_range(week_id, weeks_back)
                    items.extend(
                        database.get_must_be_done_items_multi(
                            bucket_type='week',
                            bucket_ids=week_ids,
                            include_completed=include_completed,
                        )
                    )

                if month_id:
                    month_ids = [month_id] if not include_expired else _month_ids_for_range(month_id, months_back)
                    items.extend(
                        database.get_must_be_done_items_multi(
                            bucket_type='month',
                            bucket_ids=month_ids,
                            include_completed=include_completed,
                        )
                    )

                if include_persistent:
                    items.extend(
                        database.get_must_be_done_items(
                            bucket_type='persistent',
                            bucket_id='all',
                            include_completed=include_completed,
                        )
                    )

                # Annotate expiration (items from prior day/week/month stay visible but are marked expired)
                for item in items:
                    bt = (item.get('bucket_type') or '').lower()
                    bid = str(item.get('bucket_id') or '')
                    if bt == 'today' and today_id:
                        item['expired'] = bid != str(today_id)
                    elif bt == 'week' and week_id:
                        item['expired'] = bid != str(week_id)
                    elif bt == 'month' and month_id:
                        item['expired'] = bid != str(month_id)
                    else:
                        item['expired'] = False

                # Sort: current buckets first, then expired; incomplete before complete
                def _sort_key(it: dict):
                    bt = (it.get('bucket_type') or '').lower()
                    expired = 1 if it.get('expired') else 0
                    completed = 1 if it.get('completed') else 0
                    bt_rank = 0 if bt == 'today' else (1 if bt == 'week' else (2 if bt == 'month' else 3))
                    created_at = it.get('created_at') or 0
                    return (expired, completed, bt_rank, created_at)

                items.sort(key=_sort_key)

                self._set_headers(200)
                self.wfile.write(
                    json.dumps(
                        {
                            'status': 'success',
                            'today_id': today_id,
                            'week_id': week_id,
                            'month_id': month_id,
                            'include_expired': include_expired,
                            'days_back': days_back,
                            'weeks_back': weeks_back,
                            'months_back': months_back,
                            'items': items,
                        }
                    ).encode('utf-8')
                )
                return
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return

        # Lightweight activity status for conditional dashboard refresh.
        if parsed.path == '/activity/status':
            try:
                count = database.get_activity_count()
                latest_ts = database.get_latest_activity_timestamp()
                self._set_headers(200)
                self.wfile.write(
                    json.dumps(
                        {
                            'status': 'ok',
                            'activity_count': count,
                            'latest_activity_ts': latest_ts,
                        }
                    ).encode('utf-8')
                )
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        if parsed.path != '/habits':
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))
            return

        params = parse_qs(parsed.query)
        start = params.get('start', [None])[0]
        end = params.get('end', [None])[0]
        if start is None or end is None:
            start, end = _default_start_end()

        habits = [name for name, _ in HABITS] if HABITS else None
        data = database.get_habit_completions(habits=habits, start_date=start, end_date=end)
        tz = pytz.timezone(TIMEZONE)

        for habit_map in data.values():
            for day_meta in habit_map.values():
                if not isinstance(day_meta, dict):
                    continue
                updated_raw = day_meta.get('updated_at')
                if updated_raw:
                    try:
                        if isinstance(updated_raw, (int, float)):
                            dt = datetime.datetime.fromtimestamp(float(updated_raw), tz)
                        elif isinstance(updated_raw, str):
                            parsed_dt = datetime.datetime.fromisoformat(updated_raw)
                            dt = parsed_dt.astimezone(tz) if parsed_dt.tzinfo else tz.localize(parsed_dt)
                        else:
                            dt = None
                    except Exception:
                        dt = None
                    day_meta['updated_at'] = dt.isoformat() if dt else None
                else:
                    day_meta['updated_at'] = None

        payload = {
            'habits': habits,
            'start': start,
            'end': end,
            'completions': data,
        }
        self._set_headers(200)
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def do_POST(self) -> None:  # noqa: N802
        try:
            import sys
            print(f"[habit-server] do_POST entered", flush=True)
            sys.stdout.flush()
            parsed = urlparse(self.path)
            # Log incoming path for debugging
            print(f"[habit-server] POST {parsed.path}", flush=True)
            sys.stdout.flush()
            
            content_length = int(self.headers.get('Content-Length', 0))
            print(f"[habit-server] Content-Length: {content_length}", flush=True)
            sys.stdout.flush()
        except Exception as e:
            import traceback
            print(f"[habit-server] EARLY EXCEPTION: {e}", flush=True)
            traceback.print_exc()
            return
        
        # Handle AI coach refresh FIRST, before any other routing
        if parsed.path == '/ai_coach/refresh':
            try:
                print(f"[habit-server] AI coach refresh requested", flush=True)
                agent = get_productivity_agent()
                if not agent.coach or not agent.coach.enabled:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({'error': 'AI coach not enabled'}).encode('utf-8'))
                    return
                
                # Clear the cache file to force fresh API call
                cache_file = agent.coach._advice_cache_file
                if cache_file.exists():
                    cache_file.unlink()
                    print(f"[habit-server] Cleared cache file", flush=True)
                
                # Get fresh advice
                try:
                    stats = agent.get_current_stats()
                    goals_dict = {cat: g.daily_target_minutes for cat, g in agent.goals.items()}
                    thresholds = agent._get_adaptive_thresholds()
                    waste_ratio = stats.get('wasted', 0) / max(1, sum(stats.values())) * 100 if sum(stats.values()) > 0 else 0
                    
                    print(f"[habit-server] Calling AI coach with stats: {stats}", flush=True)
                    advice, advice_ts = agent.coach.get_coaching_with_timestamp(
                        stats=stats,
                        goals=goals_dict,
                        is_rest_day=thresholds['is_rest_day'],
                        rest_reason=thresholds['rest_reason'],
                        waste_ratio=waste_ratio,
                        focus_streak=agent.state.longest_streak_today,
                        best_streak=agent.state.longest_streak_today,
                    )
                    
                    print(f"[habit-server] Got advice: {advice[:100]}...", flush=True)
                    
                    self._set_headers(200)
                    self.wfile.write(json.dumps({
                        'status': 'success',
                        'advice': advice,
                        'timestamp': advice_ts,
                        'model': agent.coach._model_name
                    }).encode('utf-8'))
                    return
                except Exception as coach_err:
                    print(f"[habit-server] AI coach error: {coach_err}", flush=True)
                    import traceback
                    traceback.print_exc()
                    self._set_headers(500)
                    self.wfile.write(json.dumps({'error': str(coach_err)}).encode('utf-8'))
                    return
            except Exception as e:
                print(f"[habit-server] AI coach refresh error: {e}", flush=True)
                import traceback
                traceback.print_exc()
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
        
        # Handle productivity goal updates
        if parsed.path == '/productivity/goals':
            length = int(self.headers.get('Content-Length', 0))
            try:
                body = self.rfile.read(length)
                payload = json.loads(body.decode('utf-8')) if body else {}
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON'}).encode('utf-8'))
                return
            
            try:
                from productivity_agent import ProductivityGoal
                agent = get_productivity_agent()
                
                category = payload.get('category', '').strip().lower()
                target_minutes = payload.get('target_minutes')
                is_positive = payload.get('is_positive', True)
                enabled = payload.get('enabled', True)
                
                if not category or target_minutes is None:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({'error': 'Missing category or target_minutes'}).encode('utf-8'))
                    return
                
                goal = ProductivityGoal(
                    category=category,
                    daily_target_minutes=int(target_minutes),
                    is_positive=is_positive,
                    enabled=enabled
                )
                agent.add_goal(goal)
                
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    'status': 'success',
                    'goal': {
                        'category': goal.category,
                        'target_minutes': goal.daily_target_minutes,
                        'is_positive': goal.is_positive,
                        'enabled': goal.enabled
                    }
                }).encode('utf-8'))
                return
            except Exception as e:
                print(f"[habit-server] Error updating goal: {e}")
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
        
        # Handle must_done updates
        if parsed.path == '/must_done/update':
            length = int(self.headers.get('Content-Length', 0))
            try:
                body = self.rfile.read(length)
                payload = json.loads(body.decode('utf-8')) if body else {}
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON'}).encode('utf-8'))
                return
            
            task_id = payload.get('task_id')
            week_id = payload.get('week_id')
            completed = payload.get('completed')
            
            if not task_id or not week_id or completed is None:
                self._set_headers(400)
                self.wfile.write(json.dumps({'error': 'Missing required fields'}).encode('utf-8'))
                return
            
            # Update the database
            import sqlite3
            import time
            try:
                conn = sqlite3.connect('data/activity.sqlite')
                cursor = conn.cursor()
                
                if completed:
                    cursor.execute('''
                        INSERT OR REPLACE INTO must_done_items (task_id, week_id, completed, completed_at)
                        VALUES (?, ?, 1, ?)
                    ''', (task_id, week_id, time.time()))
                else:
                    cursor.execute('''
                        INSERT OR REPLACE INTO must_done_items (task_id, week_id, completed, completed_at)
                        VALUES (?, ?, 0, NULL)
                    ''', (task_id, week_id))
                
                conn.commit()
                conn.close()
                
                self._set_headers(200)
                self.wfile.write(json.dumps({'status': 'success', 'task_id': task_id, 'completed': completed}).encode('utf-8'))
                return
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return

        # Handle must_be_done add/update/delete (ad-hoc todos)
        if parsed.path in ('/must_be_done/add', '/must_be_done/update', '/must_be_done/delete'):
            length = int(self.headers.get('Content-Length', 0))
            try:
                body = self.rfile.read(length)
                payload = json.loads(body.decode('utf-8')) if body else {}
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON'}).encode('utf-8'))
                return

            try:
                if parsed.path == '/must_be_done/add':
                    bucket_type = payload.get('bucket_type')
                    bucket_id = payload.get('bucket_id')
                    description = payload.get('description')
                    item = database.add_must_be_done_item(bucket_type, bucket_id, description)
                    if not item:
                        self._set_headers(400)
                        self.wfile.write(json.dumps({'error': 'Missing or invalid fields'}).encode('utf-8'))
                        return
                    self._set_headers(200)
                    self.wfile.write(json.dumps({'status': 'success', 'item': item}).encode('utf-8'))
                    return

                if parsed.path == '/must_be_done/update':
                    item_id = payload.get('id')
                    completed = payload.get('completed')
                    if item_id is None or completed is None:
                        self._set_headers(400)
                        self.wfile.write(json.dumps({'error': 'Missing id or completed'}).encode('utf-8'))
                        return
                    ok = database.set_must_be_done_item_completed(item_id, bool(completed))
                    if not ok:
                        self._set_headers(404)
                        self.wfile.write(json.dumps({'error': 'Item not found'}).encode('utf-8'))
                        return
                    self._set_headers(200)
                    self.wfile.write(json.dumps({'status': 'success', 'id': item_id, 'completed': bool(completed)}).encode('utf-8'))
                    return

                if parsed.path == '/must_be_done/delete':
                    item_id = payload.get('id')
                    if item_id is None:
                        self._set_headers(400)
                        self.wfile.write(json.dumps({'error': 'Missing id'}).encode('utf-8'))
                        return
                    ok = database.delete_must_be_done_item(item_id)
                    if not ok:
                        self._set_headers(404)
                        self.wfile.write(json.dumps({'error': 'Item not found'}).encode('utf-8'))
                        return
                    self._set_headers(200)
                    self.wfile.write(json.dumps({'status': 'success', 'id': item_id}).encode('utf-8'))
                    return
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return

        # Handle streak notes add
        if parsed.path in ('/notes/add', '/save_note'):
            length = int(self.headers.get('Content-Length', 0))
            try:
                body = self.rfile.read(length)
                payload = json.loads(body.decode('utf-8')) if body else {}
            except json.JSONDecodeError:
                self._set_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON'}).encode('utf-8'))
                return

            note = payload.get('note')
            ts = payload.get('timestamp')
            try:
                note_id = database.add_streak_note(note, ts)
                
                # Fetch updated recent notes to send back to client
                recent_notes = database.get_recent_streak_notes(5)
                notes_list = [
                    {
                        'text': note_text,
                        'timestamp': timestamp
                    }
                    for note_text, timestamp in recent_notes
                ]
                
                self._set_headers(200)
                self.wfile.write(json.dumps({
                    'status': 'success',
                    'id': note_id,
                    'recent_notes': notes_list
                }).encode('utf-8'))
                return
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return

        # Handle habit completions
        if parsed.path != '/habits':
            # Only return 404 if it's not one of the special routes we handle above
            # (This safeguard should not be reached for /ai_coach/refresh since it returns above)
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': f'Not found: {parsed.path}'}).encode('utf-8'))
            return

        length = int(self.headers.get('Content-Length', 0))
        try:
            body = self.rfile.read(length)
            payload = json.loads(body.decode('utf-8')) if body else {}
        except json.JSONDecodeError:
            self._set_headers(400)
            self.wfile.write(json.dumps({'error': 'Invalid JSON'}).encode('utf-8'))
            return

        habit = (payload.get('habit') or '').strip()
        date_str = (payload.get('date') or '').strip()
        completed = bool(payload.get('completed'))

        if not habit:
            self._set_headers(400)
            self.wfile.write(json.dumps({'error': 'Missing habit'}).encode('utf-8'))
            return

        if not date_str:
            tz = datetime.datetime.now().astimezone().date()
            date_str = tz.isoformat()

        try:
            result = database.record_habit_completion(habit, date_str, completed)
            if not result:
                print(f"[habit-server] record_habit_completion returned None for {habit} on {date_str}")
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': 'Failed to record habit'}).encode('utf-8'))
                return

            tz = pytz.timezone(TIMEZONE)
            updated_iso = None
            updated_raw = result.get('updated_at') if isinstance(result, dict) else None
            if updated_raw:
                try:
                    if isinstance(updated_raw, (int, float)):
                        dt = datetime.datetime.fromtimestamp(float(updated_raw), tz)
                    elif isinstance(updated_raw, str):
                        parsed_dt = datetime.datetime.fromisoformat(updated_raw)
                        dt = parsed_dt.astimezone(tz) if parsed_dt.tzinfo else tz.localize(parsed_dt)
                    else:
                        dt = None
                except Exception:
                    dt = None
                if dt:
                    updated_iso = dt.isoformat()

            self._set_headers(200)
            self.wfile.write(json.dumps({'status': 'ok', 'habit': habit, 'date': date_str, 'completed': completed, 'updated_at': updated_iso}).encode('utf-8'))
        except Exception as e:
            print(f"[habit-server] Exception in POST /habits: {e}")
            import traceback
            traceback.print_exc()
            self._set_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))



def run_server() -> None:
    database.initialize_database()
    print(f"Habit tracker server running at http://{HOST}:{PORT}/habits")
    httpd = ThreadingHTTPServer((HOST, PORT), HabitRequestHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down habit tracker server")
    except Exception as e:
        print(f"\n[habit-server] Server crashed with exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        httpd.server_close()


if __name__ == '__main__':
    run_server()
