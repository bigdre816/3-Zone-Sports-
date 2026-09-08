"""Cloudflare Stream video adapter, webhooks, clipping, and photo-store isolation.

Live Stream is never contacted. Tests inject a recording HTTP client.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.control_plane import AuthError, ControlPlane, ForbiddenError
from backend.db import Database
from backend.http_server import make_http_server
from backend.media_provider import (
    CloudflareStreamProvider, HttpResponse, ProviderError,
    stream_webhook_signature, verify_stream_webhook,
)
from backend.network import NetworkService
from backend.photo_storage import FakePhotoStorage, S3CompatiblePhotoStorage
from backend.portal import PortalService
from backend.seed import seed_if_empty


STREAM_TOKEN = "cf-test-token-not-for-clients"
STREAM_SECRET = "cf-webhook-secret"


class MockStreamHTTP:
    """Records Stream REST calls and returns canned TUS / direct_upload / clip replies."""

    def __init__(self):
        self.calls = []
        self.videos = {}
        self.clip_status = "inprogress"

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        headers = headers or {}
        self.calls.append({
            "method": method.upper(),
            "url": url,
            "headers": dict(headers),
            "body": body or b"",
        })
        auth = headers.get("Authorization") or headers.get("authorization") or ""
        if STREAM_TOKEN not in auth:
            return HttpResponse(401, {}, b'{"success":false}')
        path = url.split("?")[0]
        if method.upper() == "POST" and path.endswith("/stream"):
            return self._tus(headers)
        if method.upper() == "POST" and path.endswith("/stream/direct_upload"):
            return self._direct()
        if method.upper() == "POST" and path.endswith("/stream/clip"):
            return self._clip(body)
        if method.upper() == "GET" and "/stream/" in path:
            uid = path.rsplit("/", 1)[-1]
            video = self.videos.get(uid, {"uid": uid, "status": {"state": "ready"}, "duration": 10})
            return HttpResponse(200, {}, json.dumps({"success": True, "result": video}).encode())
        return HttpResponse(404, {}, b"{}")

    def _tus(self, headers):
        uid = "gameuid" + hashlib.sha256(repr(len(self.calls)).encode()).hexdigest()[:24]
        location = f"https://upload.videodelivery.net/tus/{uid}?tusv2=true"
        self.videos[uid] = {
            "uid": uid, "status": {"state": "pendingupload"}, "duration": -1,
        }
        return HttpResponse(201, {"Location": location}, json.dumps({
            "success": True, "result": {"uid": uid},
        }).encode())

    def _direct(self):
        uid = "clipuid" + hashlib.sha256(repr(len(self.calls)).encode()).hexdigest()[:24]
        upload = f"https://upload.videodelivery.net/{uid}"
        self.videos[uid] = {"uid": uid, "status": {"state": "pendingupload"}, "duration": -1}
        return HttpResponse(200, {}, json.dumps({
            "success": True,
            "result": {"uid": uid, "uploadURL": upload},
        }).encode())

    def _clip(self, body):
        payload = json.loads(body.decode()) if body else {}
        source = payload.get("clippedFromVideoUID")
        uid = "derived" + hashlib.sha256((source or "x").encode()).hexdigest()[:25]
        self.videos[uid] = {
            "uid": uid,
            "clippedFrom": source,
            "status": {"state": self.clip_status},
            "duration": float(payload.get("endTimeSeconds") or 0) - float(payload.get("startTimeSeconds") or 0),
            "readyToStream": self.clip_status == "ready",
        }
        return HttpResponse(200, {}, json.dumps({"success": True, "result": self.videos[uid]}).encode())


def build_cf():
    db = Database(":memory:")
    seed_if_empty(db)
    cfg = Config(
        env="demo",
        allowed_origins=["http://127.0.0.1", "http://localhost"],
        media_provider="cloudflare",
        cloudflare_account_id="acct123",
        cloudflare_api_token=STREAM_TOKEN,
        cloudflare_webhook_secret=STREAM_SECRET,
        fake_webhook_secret="fake-webhook-secret",
        http_host="127.0.0.1",
        http_port=0,
        max_body_bytes=64 * 1024,
        max_game_bytes=8 * 1024 * 1024 * 1024,
    )
    mock = MockStreamHTTP()
    provider = CloudflareStreamProvider(
        "acct123", STREAM_TOKEN, STREAM_SECRET, http_request=mock,
        max_game_bytes=cfg.max_game_bytes,
    )
    photos = FakePhotoStorage(webhook_secret=cfg.fake_webhook_secret)
    cp = ControlPlane(db, cfg)
    portal = PortalService(cp)
    net = NetworkService(cp, portal, provider, photos)
    return cp, portal, net, provider, mock, photos, cfg


def sign_stream(raw: bytes, secret: str = STREAM_SECRET, ts: str | None = None) -> str:
    ts = ts or str(int(time.time()))
    sig = stream_webhook_signature(secret, raw, ts)
    return f"time={ts},sig1={sig}"


class CloudflareDirectUploadTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider, self.mock, self.photos, self.cfg = build_cf()
        self.member = self.cp.get_user("demo-viewer")

    def test_game_tus_contract_bypasses_app_and_hides_token(self):
        contract = self.net.create_upload(self.member, {
            "kind": "game", "idempotency_key": "g-large", "byte_size": 2_000_000_000,
        })
        self.assertEqual(contract["upload_method"], "tus")
        self.assertTrue(contract["resumable"])
        self.assertTrue(contract["upload_url"].startswith("https://upload.videodelivery.net/tus/"))
        self.assertNotIn("/api/network", contract["upload_url"])
        blob = json.dumps(contract)
        self.assertNotIn(STREAM_TOKEN, blob)
        self.assertNotIn("api_token", blob)
        self.assertNotIn("CLOUDFLARE", blob.upper())
        tus = [c for c in self.mock.calls if c["url"].endswith("/stream") or "/stream?" in c["url"]]
        self.assertTrue(tus)
        headers = {k.lower(): v for k, v in tus[0]["headers"].items()}
        self.assertEqual(headers.get("tus-resumable"), "1.0.0")
        self.assertEqual(headers.get("upload-length"), "2000000000")
        self.assertIn("maxsizebytes", (headers.get("upload-metadata") or "").lower())
        stored = self.cp.db.query_one(
            "SELECT * FROM upload_jobs WHERE upload_job_id=?", (contract["upload_job_id"],)
        )
        self.assertEqual(stored["upload_url"], contract["upload_url"])
        again = self.net.create_upload(self.member, {"kind": "game", "idempotency_key": "g-large"})
        self.assertEqual(again["upload_job_id"], contract["upload_job_id"])
        self.assertEqual(again["upload_url"], contract["upload_url"])

    def test_clip_uses_stream_direct_upload_url(self):
        contract = self.net.create_upload(self.member, {"kind": "clip"})
        self.assertEqual(contract["upload_method"], "direct")
        self.assertTrue(contract["upload_url"].startswith("https://upload.videodelivery.net/"))
        self.assertFalse(contract["resumable"])
        paths = [c["url"] for c in self.mock.calls]
        self.assertTrue(any(u.endswith("/stream/direct_upload") for u in paths))
        self.assertNotIn(STREAM_TOKEN, json.dumps(contract))

    def test_photo_never_calls_stream(self):
        before = len(self.mock.calls)
        contract = self.net.create_upload(self.member, {"kind": "photo"})
        self.assertEqual(len(self.mock.calls), before)
        self.assertEqual(contract["upload_method"], "put")
        self.assertTrue(contract["upload_url"].startswith("https://photos.test/"))
        with self.assertRaises(ProviderError) as ctx:
            self.provider.create_direct_upload("photo")
        self.assertEqual(ctx.exception.code, "wrong_provider")


class CloudflareWebhookTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider, self.mock, self.photos, self.cfg = build_cf()
        self.member = self.cp.get_user("demo-viewer")
        self.owner = self.cp.get_user("demo-owner")

    def _ready_game(self, event_id="evt_mw_wrestling"):
        game = self.net.submit_game(self.member, {
            "sport": "basketball", "home_team_name": "Lincoln", "away_team_name": "Central",
            "rights_attestation": True, "event_id": event_id, "visibility": "private",
        })
        uid = self.cp.db.query_one(
            "SELECT provider_uid FROM upload_jobs WHERE upload_job_id=?",
            (game["upload"]["upload_job_id"],),
        )["provider_uid"]
        payload = {
            "uid": uid,
            "readyToStream": True,
            "status": {"state": "ready"},
            "duration": 600,
            "size": 123456,
            "created": "2026-09-07T00:00:00.000000Z",
            "readyToStreamAt": "2026-09-07T00:01:00.000000Z",
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        headers = {"Webhook-Signature": sign_stream(raw)}
        result = self.net.apply_webhook(headers, payload, raw_body=raw)
        self.assertEqual(result["status"], "ready")
        return self.net.game_view(self.member, game["game_id"]), uid, payload, raw

    def test_stream_signature_ready_duplicate_and_stale(self):
        game, uid, payload, raw = self._ready_game()
        self.assertEqual(game["processing_status"], "ready")
        self.assertEqual(game["duration_seconds"], 600)
        replay = self.net.apply_webhook({"Webhook-Signature": sign_stream(raw)}, payload, raw_body=raw)
        self.assertTrue(replay.get("duplicate"))
        stale = {
            "uid": uid,
            "status": {"state": "error", "errorReasonCode": "ERR_NON_VIDEO"},
            "readyToStreamAt": "2026-09-07T00:02:00.000000Z",
        }
        stale_raw = json.dumps(stale, separators=(",", ":")).encode()
        ignored = self.net.apply_webhook(
            {"Webhook-Signature": sign_stream(stale_raw)}, stale, raw_body=stale_raw,
        )
        self.assertEqual(ignored.get("ignored"), "stale")
        job = self.cp.db.query_one("SELECT status FROM upload_jobs WHERE provider_uid=?", (uid,))
        self.assertEqual(job["status"], "ready")
        with self.assertRaises(AuthError):
            self.net.apply_webhook({"Webhook-Signature": "time=1,sig1=deadbeef"}, payload, raw_body=raw)

    def test_http_webhook_route_uses_raw_body(self):
        httpd = make_http_server(
            self.cfg, self.cp, "/tmp", provider=self.provider, photo_storage=self.photos,
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            contract = self.net.create_upload(self.member, {"kind": "clip"})
            uid = self.cp.db.query_one(
                "SELECT provider_uid FROM upload_jobs WHERE upload_job_id=?",
                (contract["upload_job_id"],),
            )["provider_uid"]
            payload = {
                "uid": uid,
                "status": {"state": "ready"},
                "duration": 24,
                "readyToStreamAt": "2026-09-07T12:00:00Z",
            }
            raw = json.dumps(payload, separators=(",", ":")).encode()
            req = urllib.request.Request(
                f"http://{host}:{port}/api/network/webhooks/media",
                data=raw,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Webhook-Signature": sign_stream(raw),
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
            self.assertEqual(body["status"], "ready")
            job = self.net.upload_status(self.member, contract["upload_job_id"])
            self.assertEqual(job["status"], "ready")

            req2 = urllib.request.Request(
                f"http://{host}:{port}/api/network/webhooks/media",
                data=raw,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Webhook-Signature": "time=1,sig1=nope",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req2, timeout=5)
            self.assertEqual(ctx.exception.code, 401)

            big = b"{" + b'"uid":"' + uid.encode() + b'","pad":"' + (b"x" * 70_000) + b'"}'
            req3 = urllib.request.Request(
                f"http://{host}:{port}/api/network/uploads",
                data=big,
                method="POST",
                headers={"Content-Type": "application/json", "Authorization": "Bearer x"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req3, timeout=5)
            self.assertEqual(ctx.exception.code, 413)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_upload_http_json_has_no_file_bytes(self):
        login = self.cp.password_login("demo-viewer", "change-me-viewer-local")
        httpd = make_http_server(
            self.cfg, self.cp, "/tmp", provider=self.provider, photo_storage=self.photos,
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            raw = json.dumps({"kind": "game"}).encode()
            req = urllib.request.Request(
                f"http://{host}:{port}/api/network/uploads",
                data=raw,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {login['session_token']}",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                contract = json.loads(resp.read().decode())
            self.assertEqual(contract["upload_method"], "tus")
            self.assertNotIn("file", contract)
            self.assertLess(len(raw), 100)
        finally:
            httpd.shutdown()
            httpd.server_close()


class CloudflareClipAndRevokeTests(unittest.TestCase):
    def setUp(self):
        self.cp, self.portal, self.net, self.provider, self.mock, self.photos, self.cfg = build_cf()
        self.member = self.cp.get_user("demo-viewer")
        self.owner = self.cp.get_user("demo-owner")

    def _ready_game(self, event_id="evt_mw_wrestling"):
        game = self.net.submit_game(self.member, {
            "sport": "basketball", "home_team_name": "Lincoln", "away_team_name": "Central",
            "rights_attestation": True, "event_id": event_id,
        })
        uid = self.cp.db.query_one(
            "SELECT provider_uid FROM upload_jobs WHERE upload_job_id=?",
            (game["upload"]["upload_job_id"],),
        )["provider_uid"]
        payload = {
            "uid": uid, "status": {"state": "ready"}, "duration": 400,
            "readyToStreamAt": "2026-09-07T00:01:00Z",
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self.net.apply_webhook({"Webhook-Signature": sign_stream(raw)}, payload, raw_body=raw)
        return self.net.game_view(self.member, game["game_id"]), uid

    def test_clip_is_new_uid_source_unchanged(self):
        game, source_uid = self._ready_game()
        before = self.cp.db.query_one("SELECT * FROM games WHERE game_id=?", (game["game_id"],))
        clip = self.net.create_clip_definition(self.member, {
            "source_game_id": game["game_id"], "start_seconds": 10, "end_seconds": 30,
        })
        rendered = self.net.render_clip(self.member, clip["clip_id"])
        self.assertEqual(rendered["publication_status"], "rendering")
        derived_uid = self.cp.db.query_one(
            "SELECT provider_uid FROM media_assets WHERE media_asset_id=?",
            (rendered["derived_media_asset_id"],),
        )["provider_uid"]
        self.assertNotEqual(derived_uid, source_uid)
        clip_calls = [c for c in self.mock.calls if c["url"].endswith("/stream/clip")]
        self.assertTrue(clip_calls)
        body = json.loads(clip_calls[0]["body"].decode())
        self.assertEqual(body["clippedFromVideoUID"], source_uid)
        payload = {
            "uid": derived_uid,
            "clippedFrom": source_uid,
            "status": {"state": "ready"},
            "duration": 20,
            "readyToStreamAt": "2026-09-07T00:03:00Z",
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self.net.apply_webhook({"Webhook-Signature": sign_stream(raw)}, payload, raw_body=raw)
        after = self.cp.db.query_one("SELECT * FROM games WHERE game_id=?", (game["game_id"],))
        self.assertEqual(before["media_asset_id"], after["media_asset_id"])
        self.assertEqual(before["duration_seconds"], after["duration_seconds"])
        source_asset = self.cp.db.query_one(
            "SELECT provider_uid FROM media_assets WHERE media_asset_id=?",
            (before["media_asset_id"],),
        )
        self.assertEqual(source_asset["provider_uid"], source_uid)
        ready = self.net.clip_view(self.member, clip["clip_id"])
        self.assertEqual(ready["publication_status"], "ready")
        self.assertNotEqual(ready["derived_media_asset_id"], before["media_asset_id"])
        again = self.net.render_clip(self.member, clip["clip_id"])
        self.assertEqual(again["provider_job_id"], rendered["provider_job_id"])
        self.assertEqual(len([c for c in self.mock.calls if c["url"].endswith("/stream/clip")]), 1)

    def test_revoke_blocks_playback_and_publish_source_remains(self):
        game, source_uid = self._ready_game()
        clip = self.net.create_clip_definition(self.member, {
            "source_game_id": game["game_id"], "start_seconds": 0, "end_seconds": 20,
        })
        rendered = self.net.render_clip(self.member, clip["clip_id"])
        derived_uid = self.cp.db.query_one(
            "SELECT provider_uid FROM media_assets WHERE media_asset_id=?",
            (rendered["derived_media_asset_id"],),
        )["provider_uid"]
        payload = {
            "uid": derived_uid, "clippedFrom": source_uid,
            "status": {"state": "ready"}, "duration": 20,
            "readyToStreamAt": "2026-09-07T00:04:00Z",
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self.net.apply_webhook({"Webhook-Signature": sign_stream(raw)}, payload, raw_body=raw)
        self.cp.revoke_rights("evt_mw_wrestling", self.owner, "stop")
        with self.assertRaises(ForbiddenError):
            self.net.game_playback(self.member, game["game_id"])
        with self.assertRaises(ForbiddenError) as ctx:
            self.net.publish_clip(self.member, clip["clip_id"], {"visibility": "public"})
        self.assertEqual(ctx.exception.code, "rights_exceeded")
        still = self.cp.db.query_one("SELECT * FROM games WHERE game_id=?", (game["game_id"],))
        self.assertEqual(
            self.cp.db.query_one(
                "SELECT provider_uid FROM media_assets WHERE media_asset_id=?",
                (still["media_asset_id"],),
            )["provider_uid"],
            source_uid,
        )


class PhotoStorageAdapterTests(unittest.TestCase):
    def test_s3_presign_is_put_not_stream(self):
        store = S3CompatiblePhotoStorage(
            "https://s3.example.test", "media-bucket", "AKIAFAKE", "secret-key", region="auto",
        )
        contract = store.create_direct_upload("photo")
        self.assertEqual(contract["upload_method"], "put")
        self.assertIn("media-bucket", contract["upload_url"])
        self.assertIn("X-Amz-Signature=", contract["upload_url"])
        self.assertIn("/photos/", contract["upload_url"])
        self.assertNotIn("videodelivery", contract["upload_url"])
        self.assertNotIn("cloudflare", contract["upload_url"].lower())
        self.assertNotIn("AKIAFAKE", json.dumps({k: v for k, v in contract.items() if k != "upload_url"}))


class StreamSignatureUnitTests(unittest.TestCase):
    def test_verify_raw_body_not_reserialized(self):
        raw = b'{"uid":"abc","status":{"state":"ready"}}'
        header = sign_stream(raw)
        self.assertTrue(verify_stream_webhook(STREAM_SECRET, {"Webhook-Signature": header}, raw))
        shuffled = b'{"status":{"state":"ready"},"uid":"abc"}'
        self.assertFalse(verify_stream_webhook(STREAM_SECRET, {"Webhook-Signature": header}, shuffled))


@unittest.skipUnless(
    os.environ.get("TZ_CLOUDFLARE_ACCOUNT_ID") and os.environ.get("TZ_CLOUDFLARE_API_TOKEN"),
    "live Cloudflare credentials not configured",
)
class LiveCloudflareSmoke(unittest.TestCase):
    def test_create_clip_direct_upload_smoke(self):
        provider = CloudflareStreamProvider(
            os.environ["TZ_CLOUDFLARE_ACCOUNT_ID"],
            os.environ["TZ_CLOUDFLARE_API_TOKEN"],
            os.environ.get("TZ_CLOUDFLARE_WEBHOOK_SECRET", ""),
        )
        contract = provider.create_direct_upload("clip", max_duration_seconds=5, max_bytes=1_000_000)
        self.assertIn("upload_url", contract)
        self.assertNotEqual(contract["upload_url"], "")
        self.assertNotIn(os.environ["TZ_CLOUDFLARE_API_TOKEN"], json.dumps(contract))


if __name__ == "__main__":
    unittest.main(verbosity=2)
