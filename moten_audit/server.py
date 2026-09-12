"""Same-origin HTTP server for the Moten control-plane and audit department."""

from __future__ import annotations

import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .db import Database
from .service import AuditService

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Handler(BaseHTTPRequestHandler):
    service: AuditService

    def log_message(self, *_args):
        return  # never log request bodies; payloads may be restricted

    def _send(self, status: int, value: dict):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 128 * 1024:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        value = json.loads(raw or b"{}")
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def _role(self) -> str:
        return self.headers.get("X-Moten-Role", "IP Steward")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/onchain/health":
                return self._send(200, self.service.health())
            if path == "/api/audit/events":
                return self._send(200, {"events": self.service.list_events()})
            if path == "/api/onchain/publications":
                return self._send(200, {"publications": self.service.list_requests()})
            if path == "/api/onchain/receipts":
                return self._send(200, {"receipts": self.service.list_receipts()})
            if path == "/api/onchain/signing-profile":
                return self._send(200, {"signing_profile": self.service.signing_profile()})
            match = re.fullmatch(r"/api/audit/events/([^/]+)", path)
            if match:
                event = self.service.get_event(match.group(1))
                return self._send(200 if event else 404, {"event": event} if event else {"error": "not found"})
            match = re.fullmatch(r"/api/onchain/receipts/([^/]+)", path)
            if match:
                return self._send(200, {"receipts": self.service.receipts(match.group(1))})
            match = re.fullmatch(r"/api/onchain/publications/([^/]+)", path)
            if match:
                publication = self.service.publication(match.group(1))
                return self._send(200 if publication else 404, {"publication": publication} if publication else {"error": "not found"})
            match = re.fullmatch(r"/api/onchain/transactions/([^/]+)", path)
            if match:
                row = self.service.db.one("SELECT * FROM blockchain_receipts WHERE transaction_hash=?", (match.group(1),))
                return self._send(200 if row else 404, {"receipt": dict(row) if row else None} if row else {"error": "not found"})
            match = re.fullmatch(r"/api/onchain/reconciliation/([^/]+)", path)
            if match:
                row = self.service.db.one("SELECT * FROM reconciliation_runs WHERE run_id=?", (match.group(1),))
                return self._send(200 if row else 404, {"reconciliation": dict(row) if row else None} if row else {"error": "not found"})
            match = re.fullmatch(r"/api/treasure/verifications/([^/]+)", path)
            if match:
                verification = self.service.get_verification(match.group(1))
                return self._send(200 if verification else 404, {"verification": verification} if verification else {"error": "not found"})
            return self._static(path)
        except Exception as exc:
            return self._send(500, {"error": str(exc)})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self._body()
            if path == "/api/audit/events":
                return self._send(201, {"event": self.service.create_event(body)})
            match = re.fullmatch(r"/api/treasure/verifications/([^/]+)", path)
            if match:
                return self._send(201, {"verification": self.service.verify(match.group(1))})
            if path == "/api/onchain/publications":
                request = self.service.request_publication(body["event_id"], body["verification_id"], self._role())
                return self._send(201, {"publication": request})
            match = re.fullmatch(r"/api/onchain/publications/([^/]+)/(approve|retry)", path)
            if match:
                return self._send(200, {"publication": self.service.publish(match.group(1))})
            match = re.fullmatch(r"/api/onchain/publications/([^/]+)/hold", path)
            if match:
                return self._send(200, {"publication": self.service.hold_publication(match.group(1), self._role())})
            if path == "/api/onchain/reconcile":
                return self._send(201, self.service.reconcile())
            if path == "/api/onchain/signing-profile/account":
                return self._send(200, {"signing_profile": self.service.set_signing_account(
                    body.get("account", ""), body.get("network"))})
            if path == "/api/onchain/publications/wallet-confirm":
                return self._send(200, self.service.confirm_wallet_publication(
                    body.get("request_id", ""),
                    tx_hash=body.get("transaction_hash") or body.get("tx_hash") or "",
                    account=body.get("account", ""),
                    network=body.get("network"),
                ))
            return self._send(404, {"error": "not found"})
        except PermissionError as exc:
            return self._send(403, {"error": str(exc)})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception:
            return self._send(500, {"error": "internal error"})

    def do_HEAD(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            return self._send(200, {"ok": True})
        return self._static(path, body=False)

    def _static(self, path: str, body: bool = True):
        if path in {"/", "/index.html"}:
            filename = "index.html"
            content_type = "text/html; charset=utf-8"
        elif path == "/System":
            filename = "System"
            content_type = "text/html; charset=utf-8"
        else:
            filename = path.lstrip("/")
            content_type = None
        full = os.path.abspath(os.path.join(ROOT, filename))
        if not full.startswith(ROOT + os.sep) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as file:
            raw = file.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(full)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(raw)


def serve() -> None:
    config = Config.from_env()
    database = Database(config.database_path)
    service = AuditService(database, config)
    handler = type("MotenHandler", (Handler,), {"service": service})
    host, port = os.getenv("HOST", "0.0.0.0"), int(os.getenv("PORT", "8000"))
    print(f"Moten On-Chain Audit Department on http://{host}:{port} ({config.xrpl_mode})", flush=True)
    ThreadingHTTPServer((host, port), handler).serve_forever()

