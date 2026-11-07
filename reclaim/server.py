"""Local-first crypto intelligence service. Requires no external Python packages."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import csv
import hmac
import io
import json
import os
import sqlite3
import threading
from urllib.parse import urlparse

from engine import CHAINS, discover_block, fetch_prices, liquidation_simulator, scan_wallet, validate_address, validate_chain

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.environ.get("DB_PATH", str(ROOT / "recovery.db"))).resolve()
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
APP_TOKEN = os.environ.get("APP_TOKEN", "")
DB_LOCK = threading.RLock()


def db():
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    return con


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript("""
        create table if not exists wallets (
          id integer primary key autoincrement, chain text not null,
          address text not null, label text not null default '',
          source text not null default 'manual',
          created_at text not null default (datetime('now')),
          unique(chain,address)
        );
        create table if not exists observations (
          id integer primary key autoincrement,
          wallet_id integer not null references wallets(id) on delete cascade,
          scanned_at text not null, native_balance text not null,
          usdc_balance text not null, estimated_usd text,
          price_status text not null,
          last_activity text,
          unique(wallet_id,scanned_at)
        );
        create index if not exists observations_wallet on observations(wallet_id,id desc);
        """)


def add_wallets(chain, addresses, source="manual"):
    validate_chain(chain)
    if not isinstance(addresses, list) or len(addresses) > 100:
        raise ValueError("Supply at most 100 addresses")
    if not isinstance(source, str) or source not in ("manual", "historical_block"):
        raise ValueError("Unsupported source")
    normalized = list(dict.fromkeys(validate_address(a) for a in addresses))
    with DB_LOCK, db() as c:
        for a in normalized:
            c.execute("insert or ignore into wallets(chain,address,source) values(?,?,?)", (chain, a, source))
    return normalized


def query_wallets():
    with db() as c:
        rows = c.execute("""
        select w.id,w.chain,w.address,w.label,w.source,w.created_at,
               o.native_balance,o.usdc_balance,o.estimated_usd,o.price_status,o.scanned_at,o.last_activity
        from wallets w left join observations o on o.id = (
          select max(id) from observations where wallet_id=w.id
        ) order by w.id desc limit 5000
        """).fetchall()
    return [dict(row) for row in rows]


def scan_ids(ids):
    if not isinstance(ids, list) or len(ids) > 25 or any(isinstance(v, bool) or not isinstance(v, int) for v in ids):
        raise ValueError("Select up to 25 wallet IDs")
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise ValueError("Select at least one wallet")
    with db() as c:
        wallets = [dict(r) for r in c.execute(
            f"select id,chain,address from wallets where id in ({','.join('?' for _ in ids)})", ids
        ).fetchall()]
    if len(wallets) != len(ids):
        raise ValueError("One or more wallet IDs do not exist")
    try:
        prices = fetch_prices()
    except (RuntimeError, ValueError):
        prices = {}
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {pool.submit(scan_wallet, w["chain"], w["address"], prices): w for w in wallets}
        for future in as_completed(future_map):
            w = future_map[future]
            try:
                scan = future.result()
                with DB_LOCK, db() as c:
                    c.execute("""insert into observations(wallet_id,scanned_at,native_balance,usdc_balance,estimated_usd,price_status,last_activity)
                    values(?,?,?,?,?,?,?)""", (w["id"], scan["scanned_at"], scan["native_balance"], scan["usdc_balance"], scan["estimated_usd"], scan["price_status"], scan["last_activity"]))
                results.append({"id": w["id"], "status": "ok", **scan})
            except Exception as exc:
                results.append({"id": w["id"], "status": "error", "message": str(exc)[:220]})
    return sorted(results, key=lambda x: x["id"])


class Handler(BaseHTTPRequestHandler):
    server_version = "RecoveryEngine/0.1"

    def _headers(self, status=200, mimetype="application/json; charset=utf-8", length=None):
        self.send_response(status)
        self.send_header("Content-Type", mimetype)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, payload, status=200):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self._headers(status, length=len(raw))
        self.wfile.write(raw)

    def _authorized(self):
        if not APP_TOKEN:
            return True  # only allowed when bound to loopback; enforced at startup
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, "Bearer " + APP_TOKEN)

    def _body(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid body length")
        if size <= 0 or size > 250_000:
            raise ValueError("JSON body must be between 1 and 250000 bytes")
        obj = json.loads(self.rfile.read(size))
        if not isinstance(obj, dict):
            raise ValueError("JSON body must be an object")
        return obj

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/styles.css", "/app.js"):
            actual = STATIC / ("index.html" if path == "/" else path.lstrip("/"))
            kind = "text/html; charset=utf-8" if actual.suffix == ".html" else "text/css; charset=utf-8" if actual.suffix == ".css" else "text/javascript; charset=utf-8"
            raw = actual.read_bytes()
            self._headers(200, kind, len(raw))
            self.wfile.write(raw)
            return
        if not self._authorized():
            self._json({"error": "Access token required"}, 401)
            return
        try:
            if path == "/api/health":
                self._json({"ok": True, "mode": "read_only", "storage": "sqlite", "chains": list(CHAINS)})
            elif path == "/api/wallets":
                self._json({"wallets": query_wallets()})
            elif path == "/api/chains":
                self._json({"chains": [{"id": key, "name": val["label"], "symbol": val["symbol"]} for key, val in CHAINS.items()]})
            elif path == "/api/export.csv":
                stream = io.StringIO()
                rows = query_wallets()
                cols = ("chain", "address", "label", "source", "native_balance", "usdc_balance", "estimated_usd", "price_status", "scanned_at")
                writer = csv.DictWriter(stream, fieldnames=cols, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({col: "'" + str(row[col]) if str(row[col]).startswith(("=", "+", "-", "@")) else row[col] for col in cols})
                raw = stream.getvalue().encode("utf-8")
                self._headers(200, "text/csv; charset=utf-8", len(raw))
                self.wfile.write(raw)
            else:
                self._json({"error": "Not found"}, 404)
        except Exception:
            self._json({"error": "Unable to complete request"}, 500)

    def do_POST(self):
        if not self._authorized():
            self._json({"error": "Access token required"}, 401)
            return
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/wallets":
                normalized = add_wallets(body.get("chain", "ethereum"), body.get("addresses", []))
                self._json({"added_or_existing": len(normalized), "wallets": query_wallets()})
            elif path == "/api/scan":
                self._json({"results": scan_ids(body.get("ids", []))})
            elif path == "/api/discover":
                chain = validate_chain(body.get("chain", "ethereum"))
                block = body.get("block_number")
                addresses = discover_block(chain, block, maximum=75)
                add_wallets(chain, addresses, source="historical_block")
                self._json({"discovered": len(addresses), "block_number": block, "addresses": addresses})
            elif path == "/api/simulate":
                self._json(liquidation_simulator(body))
            else:
                self._json({"error": "Not found"}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": "Operation failed: " + str(exc)[:180]}, 502)

    def log_message(self, fmt, *args):
        # Avoid emitting wallet addresses, request bodies or tokens to logs.
        pass


def main():
    if HOST not in ("127.0.0.1", "localhost", "::1") and not APP_TOKEN:
        raise SystemExit("Refusing network bind without APP_TOKEN. Set a strong token or use HOST=127.0.0.1")
    initialize()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Recovery Engine running at http://{HOST}:{PORT} [read-only; execution disabled]", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.server_close()


if __name__ == "__main__":
    main()
