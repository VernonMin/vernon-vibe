#!/usr/bin/env python3
import json
import sqlite3
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "observability.db"


class Storage:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp REAL NOT NULL,
                attrs TEXT
            );
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp REAL NOT NULL,
                tags TEXT
            );
            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                span_id TEXT NOT NULL,
                parent_span_id TEXT,
                service TEXT NOT NULL,
                operation TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                status TEXT NOT NULL,
                timestamp REAL NOT NULL,
                attrs TEXT
            );
            """
        )
        self.conn.commit()

    def ingest_log(self, payload):
        self.conn.execute(
            "INSERT INTO logs(service, level, message, timestamp, attrs) VALUES(?,?,?,?,?)",
            (
                payload["service"],
                payload["level"],
                payload["message"],
                payload.get("timestamp", time.time()),
                json.dumps(payload.get("attrs", {})),
            ),
        )
        self.conn.commit()

    def ingest_metric(self, payload):
        self.conn.execute(
            "INSERT INTO metrics(service, name, value, timestamp, tags) VALUES(?,?,?,?,?)",
            (
                payload["service"],
                payload["name"],
                float(payload["value"]),
                payload.get("timestamp", time.time()),
                json.dumps(payload.get("tags", {})),
            ),
        )
        self.conn.commit()

    def ingest_trace(self, payload):
        self.conn.execute(
            """
            INSERT INTO traces(trace_id, span_id, parent_span_id, service, operation, duration_ms, status, timestamp, attrs)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["trace_id"],
                payload["span_id"],
                payload.get("parent_span_id"),
                payload["service"],
                payload["operation"],
                float(payload["duration_ms"]),
                payload.get("status", "ok"),
                payload.get("timestamp", time.time()),
                json.dumps(payload.get("attrs", {})),
            ),
        )
        self.conn.commit()

    def overview(self, minutes=60):
        since = time.time() - minutes * 60
        cur = self.conn.cursor()
        counts = {
            "logs": cur.execute("SELECT COUNT(*) c FROM logs WHERE timestamp >= ?", (since,)).fetchone()["c"],
            "metrics": cur.execute("SELECT COUNT(*) c FROM metrics WHERE timestamp >= ?", (since,)).fetchone()["c"],
            "traces": cur.execute("SELECT COUNT(*) c FROM traces WHERE timestamp >= ?", (since,)).fetchone()["c"],
        }
        top_services = [
            dict(r)
            for r in cur.execute(
                """
                SELECT service, COUNT(*) AS events
                FROM (
                    SELECT service, timestamp FROM logs
                    UNION ALL
                    SELECT service, timestamp FROM metrics
                    UNION ALL
                    SELECT service, timestamp FROM traces
                )
                WHERE timestamp >= ?
                GROUP BY service
                ORDER BY events DESC
                LIMIT 8
                """,
                (since,),
            ).fetchall()
        ]
        p95_by_service = [
            dict(r)
            for r in cur.execute(
                """
                SELECT service,
                    AVG(duration_ms) AS avg_duration,
                    MAX(duration_ms) AS max_duration,
                    COUNT(*) AS span_count
                FROM traces
                WHERE timestamp >= ?
                GROUP BY service
                ORDER BY span_count DESC
                LIMIT 8
                """,
                (since,),
            ).fetchall()
        ]
        recent_logs = [
            dict(r)
            for r in cur.execute(
                """
                SELECT service, level, message, timestamp
                FROM logs
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 20
                """,
                (since,),
            ).fetchall()
        ]
        return {
            "window_minutes": minutes,
            "counts": counts,
            "top_services": top_services,
            "trace_stats": p95_by_service,
            "recent_logs": recent_logs,
        }

    def metrics_timeseries(self, name, minutes=60):
        since = time.time() - minutes * 60
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT CAST(timestamp/60 AS INTEGER)*60 AS bucket, AVG(value) AS avg_value
            FROM metrics
            WHERE timestamp >= ? AND name = ?
            GROUP BY bucket
            ORDER BY bucket
            """,
            (since, name),
        ).fetchall()
        return [dict(r) for r in rows]


storage = Storage(DB_PATH)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw or b"{}")

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/ingest/logs":
                storage.ingest_log(payload)
            elif path == "/ingest/metrics":
                storage.ingest_metric(payload)
            elif path == "/ingest/traces":
                storage.ingest_trace(payload)
            elif path == "/demo/generate":
                generate_demo_data(payload.get("service", "checkout"))
            else:
                self._json(404, {"error": "Not found"})
                return
            self._json(201, {"ok": True})
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/overview":
            minutes = int(parse_qs(parsed.query).get("minutes", ["60"])[0])
            self._json(200, storage.overview(minutes))
            return

        if path == "/api/metrics":
            q = parse_qs(parsed.query)
            name = q.get("name", ["request_per_second"])[0]
            minutes = int(q.get("minutes", ["60"])[0])
            self._json(200, {"name": name, "series": storage.metrics_timeseries(name, minutes)})
            return

        if path == "/":
            path = "/index.html"

        file_path = STATIC_DIR / path.lstrip("/")
        if file_path.exists() and file_path.is_file():
            content = file_path.read_bytes()
            ctype = "text/plain"
            if file_path.suffix == ".html":
                ctype = "text/html; charset=utf-8"
            elif file_path.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif file_path.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_response(404)
        self.end_headers()


def generate_demo_data(service):
    now = time.time()
    for i in range(120):
        ts = now - (120 - i) * 30
        storage.ingest_metric(
            {
                "service": service,
                "name": "request_per_second",
                "value": 60 + (i % 15) * 2 + (i % 3),
                "timestamp": ts,
                "tags": {"env": "prod"},
            }
        )
        storage.ingest_trace(
            {
                "trace_id": f"trace-{i}",
                "span_id": f"span-{i}",
                "service": service,
                "operation": "GET /api/order",
                "duration_ms": 50 + (i % 9) * 15,
                "status": "error" if i % 17 == 0 else "ok",
                "timestamp": ts,
            }
        )
        if i % 7 == 0:
            storage.ingest_log(
                {
                    "service": service,
                    "level": "ERROR" if i % 21 == 0 else "INFO",
                    "message": "payment gateway slow" if i % 21 == 0 else "order processed",
                    "timestamp": ts,
                }
            )


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print("Observability server running at http://0.0.0.0:8000")
    server.serve_forever()
