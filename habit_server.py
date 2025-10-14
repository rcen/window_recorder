"""Simple local HTTP server to record and retrieve habit completions."""
from __future__ import annotations

import json
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import database
from config import TIMEZONE, HABITS
import pytz

HOST = '127.0.0.1'
PORT = 8042


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

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Reduce noise by logging to stdout once per request
        print("[habit-server]" , self.address_string(), format % args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._set_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
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
        parsed = urlparse(self.path)
        if parsed.path != '/habits':
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))
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

        result = database.record_habit_completion(habit, date_str, completed)
        if not result:
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


def run_server() -> None:
    database.initialize_database()
    print(f"Habit tracker server running at http://{HOST}:{PORT}/habits")
    httpd = ThreadingHTTPServer((HOST, PORT), HabitRequestHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down habit tracker server")
    finally:
        httpd.server_close()


if __name__ == '__main__':
    run_server()
