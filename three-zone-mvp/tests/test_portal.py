import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import Config
from backend.control_plane import ControlPlane, ForbiddenError, AuthError, ValidationError, ConflictError
from backend.db import Database
from backend.portal import PortalService
from backend.seed import seed_if_empty


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        seed_if_empty(self.db)
        self.cp = ControlPlane(self.db, Config(env="demo", allowed_origins=["http://localhost"]))
        self.portal = PortalService(self.cp)
        self.member = self.cp.get_user("demo-viewer")
        self.operator = self.cp.get_user("demo-owner")

    def session(self):
        return self.portal.complete_auth("demo-viewer")

    def test_verified_member_gets_server_session_and_live_lease(self):
        session = self.session()
        result = self.portal.playback(session["session_id"], "evt_mw_basketball")
        self.assertTrue(result["allow"])
        self.assertTrue(self.cp.validate_lease("evt_mw_basketball", result["lease_token"])["valid"])

    def test_unverified_member_is_denied(self):
        with self.assertRaises(ForbiddenError):
            self.portal.session("not-a-session")

    def test_expired_or_revoked_verification_denies_playback(self):
        session = self.session()
        self.db.execute("UPDATE member_verifications SET status='REVOKED' WHERE verification_id=?",
                        (session["verification"]["verification_id"],))
        with self.assertRaises(ForbiddenError):
            self.portal.playback(session["session_id"], "evt_mw_basketball")

    def test_revoked_rights_rejects_future_media(self):
        session = self.session()
        lease = self.portal.playback(session["session_id"], "evt_mw_basketball")
        self.cp.revoke_rights("evt_mw_basketball", self.operator, "stop")
        self.assertFalse(self.cp.validate_lease("evt_mw_basketball", lease["lease_token"])["valid"])

    def test_schedule_upload_preserves_prior_version_and_rejects_bad_rows(self):
        self.portal._ensure_catalog()
        bad = b"school,team,sport,level,opponent,date,start time,location,home/away,season\nLincoln High,Lincoln Freshman Basketball,basketball,freshman,Central,,19:00,Gym,HOME,2026\n"
        self.assertFalse(self.portal.upload_schedule(self.operator, "bad.csv", bad)["accepted"])
        good = b"school,team,sport,level,opponent,date,start time,location,home/away,season\nLincoln High,Lincoln Freshman Basketball,basketball,freshman,Central,2026-12-01,19:00,Gym,HOME,2026\n"
        first = self.portal.upload_schedule(self.operator, "good.csv", good)
        second = self.portal.upload_schedule(self.operator, "corrected.csv", good)
        self.assertTrue(first["accepted"]); self.assertEqual(second["version"], first["version"] + 1)
        self.assertEqual(len(self.db.query("SELECT * FROM schedule_versions WHERE schedule_id=?", (first["schedule_id"],))), second["version"])

    def test_schedule_upload_seeds_catalog_for_control_plane_import(self):
        sample = b"school,team,sport,level,opponent,date,start time,location,home/away,season\nLincoln High,Lincoln Freshman Basketball,basketball,freshman,West,2026-11-12,19:00,Lincoln Gym,HOME,2026\n"
        result = self.portal.upload_schedule(self.operator, "lincoln-2026.csv", sample)
        self.assertTrue(result["accepted"])
        self.assertFalse(result.get("errors"))

    def test_audit_persists_before_simulated_xrpl_receipt(self):
        session = self.session()
        self.portal.playback(session["session_id"], "evt_mw_basketball")
        audit = self.db.query_one("SELECT * FROM audit_events WHERE event_type='lease.issued'")
        self.assertIsNotNone(audit)
        self.portal.publish_pending()
        publication = self.db.query_one("SELECT * FROM xrpl_publications WHERE audit_event_id=?", (audit["event_id"],))
        self.assertEqual(publication["status"], "VALIDATED")
        self.assertTrue(publication["simulated"])

    def test_public_configuration_never_exposes_xrpl_secret(self):
        config = Config(env="demo", xrpl_signing_secret="do-not-show", allowed_origins=["http://localhost"])
        self.assertNotIn("do-not-show", str(config.public_config()))

    def test_catalog_seed_survives_concurrent_first_load(self):
        import threading
        errors = []

        def load():
            try:
                self.portal.live(self.member)
                self.portal.schedules(self.member)
                self.portal.archives(self.member)
            except Exception as exc:  # noqa: BLE001 - collect any worker failure
                errors.append(exc)

        threads = [threading.Thread(target=load) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(self.portal.live(self.member)), 1)
        self.assertGreaterEqual(len(self.portal.schedules(self.member)), 1)
        self.assertGreaterEqual(len(self.portal.archives(self.member)), 1)

    def test_password_login_all_seeded_roles(self):
        from backend.config import DEMO_SEED_PASSWORDS
        for username, home in (("demo-viewer", "/"), ("demo-worker", "/ops"), ("demo-owner", "/ops")):
            result = self.cp.password_login(username, DEMO_SEED_PASSWORDS[username])
            self.assertEqual(result["home"], home)
            self.assertEqual(result["user"]["user_id"], username)
            self.assertTrue(result["session_token"])

    def test_password_login_rejects_bad_password(self):
        with self.assertRaises(AuthError) as ctx:
            self.cp.password_login("demo-owner", "wrong-password")
        self.assertEqual(ctx.exception.code, "invalid_credentials")

    def test_register_viewer_can_play_and_cannot_be_staff(self):
        created = self.cp.register_viewer("pat-member", "password123", "Pat")
        self.assertEqual(created["user"]["role"], "viewer")
        self.assertEqual(created["home"], "/")
        session = self.portal.complete_auth("pat-member")
        lease = self.portal.playback(session["session_id"], "evt_mw_basketball")
        self.assertTrue(lease["allow"])
        with self.assertRaises(ValidationError):
            self.cp.register_viewer("demo-owner", "password123", "Nope")
        with self.assertRaises(ConflictError):
            self.cp.register_viewer("pat-member", "password123", "Pat")

    def test_owner_issues_staff_and_members_cannot(self):
        owner = self.cp.get_user("demo-owner")
        worker = self.cp.get_user("demo-worker")
        viewer = self.cp.get_user("demo-viewer")
        issued = self.cp.issue_staff(owner, "andre-ops", "password123", "Andre", "owner")
        self.assertEqual(issued["user"]["role"], "owner")
        self.assertEqual(issued["user"]["user_id"], "andre-ops")
        login = self.cp.password_login("andre-ops", "password123")
        self.assertEqual(login["home"], "/ops")
        with self.assertRaises(ForbiddenError) as ctx:
            self.cp.issue_staff(worker, "new-worker", "password123", "Worker", "operator")
        self.assertEqual(ctx.exception.code, "owner_required")
        with self.assertRaises(ForbiddenError):
            self.cp.issue_staff(viewer, "new-worker", "password123", "Worker", "operator")
        with self.assertRaises(ValidationError):
            self.cp.issue_staff(owner, "demo-owner", "password123", "Nope", "owner")
        with self.assertRaises(ValidationError):
            self.cp.issue_staff(owner, "new-admin", "password123", "Nope", "admin")

    def test_control_plane_app_js_is_preserved(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "backend", "static", "app.js"), encoding="utf-8") as handle:
            app_js = handle.read()
        self.assertIn("async function revokeRights()", app_js)
        self.assertIn("async function goLiveWithCamera()", app_js)
        self.assertIn("/api/events/${state.selected}/camera/attach", app_js)
        self.assertIn("async function loadInventory()", app_js)
        self.assertIn("async function loadMastery()", app_js)
        self.assertIn("async function restoreSession()", app_js)
        self.assertIn("async function issueStaff(form)", app_js)
        self.assertIn("/api/owner/staff", app_js)
        self.assertIn("res.session_token", app_js)
        self.assertNotIn("if (!state.session) return;", app_js)
        self.assertIn('querySelectorAll("#app [data-pane]")', app_js)
        self.assertIn("POST", app_js)
        self.assertGreater(len(app_js.splitlines()), 500)

    def test_investment_tracker_is_not_on_the_site(self):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertTrue(os.path.exists(os.path.join(repo, "System")))
        with open(os.path.join(repo, ".cursor", "serve.py"), encoding="utf-8") as handle:
            serve = handle.read()
        self.assertIn("Sports Access", serve)
        self.assertNotIn("Investment Tracker", serve)
        static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "static")
        for name in os.listdir(static):
            if not name.endswith(".html"):
                continue
            with open(os.path.join(static, name), encoding="utf-8") as handle:
                self.assertNotIn("Investment Tracker", handle.read())

    def test_live_render_blueprint_is_docker_demo_member_app(self):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(repo, "render.yaml"), encoding="utf-8") as handle:
            blueprint = handle.read()
        self.assertIn("runtime: docker", blueprint)
        self.assertIn("dockerfilePath: ./Dockerfile", blueprint)
        self.assertIn("healthCheckPath: /api/health", blueprint)
        self.assertIn("name: three-zone-sports", blueprint)
        self.assertIn("branch: main", blueprint)
        self.assertIn("autoDeployTrigger: commit", blueprint)
        self.assertIn("TZ_ENV", blueprint)
        self.assertIn("demo", blueprint)
        self.assertNotIn("runtime: python", blueprint)
        self.assertNotIn("TZ_ENV=production", blueprint)
        self.assertIn("mountPath: /data", blueprint)
        self.assertIn("TZ_DATABASE_PATH", blueprint)
        self.assertIn("/data/three_zone.sqlite3", blueprint)

    def test_member_site_keeps_network_shell_and_wired_watch(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static = os.path.join(root, "backend", "static")
        with open(os.path.join(static, "index.html"), encoding="utf-8") as handle:
            html = handle.read()
        for needle in ("Feed", "Live", "Inbox", "Profile", "Create",
                       "MEMBERS PORTAL", "Welcome back", "Sports Access",
                       "id=\"search-results\"", "id=\"view-about\"", "Watch it. Save it."):
            self.assertIn(needle, html)
        with open(os.path.join(static, "portal.js"), encoding="utf-8") as handle:
            js = handle.read()
        self.assertIn("Watch live", js)
        self.assertIn("pendingPlayback()", js)
        self.assertIn("location.hash = href || link.dataset.view", js)
        self.assertIn("Watch archive", js)
        self.assertIn("/api/member/archive/", js)
        self.assertIn("search-results", js)
        self.assertIn("attachPortalMedia", js)
        self.assertIn("view-sessions", js)
        self.assertIn("/vendor/hls.min.js", html)
        self.assertNotIn("?lease=", js)

    def test_upcoming_green_event_is_not_playable(self):
        with self.assertRaises(ForbiddenError) as ctx:
            self.portal.playback(self.session()["session_id"], "evt_mw_hockey")
        self.assertIn(ctx.exception.code, ("not_playable", "playback_denied"))

    def test_archive_playback_issues_lease(self):
        self.portal._ensure_catalog()
        result = self.portal.playback(self.session()["session_id"], "evt_mw_wrestling", use="archive")
        self.assertTrue(result["allow"])
        self.assertEqual(result["mode"], "archive")
        self.assertTrue(self.cp.validate_lease("evt_mw_wrestling", result["lease_token"])["valid"])

    def test_search_returns_stable_ids_and_archives(self):
        hits = self.portal.search(self.member, "lincoln")
        self.assertTrue(any(item["kind"] == "school" and item["id"] == "school_lincoln" for item in hits))
        self.assertTrue(any(item["kind"] == "game" and item["id"] == "evt_mw_basketball" for item in hits))
        wrestling = self.portal.search(self.member, "wrestling")
        self.assertTrue(any(item["kind"] == "archive" and item["id"] == "arc-central-wrestling" for item in wrestling))

    def test_archive_http_playback_sets_lease_cookie_not_json_token(self):
        import json
        import threading
        import urllib.request

        from backend.config import DEMO_SEED_PASSWORDS
        from backend.http_server import make_http_server

        cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                     allowed_origins=["http://127.0.0.1"])
        httpd = make_http_server(cfg, self.cp, "/tmp")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            base = f"http://{host}:{port}"
            login = urllib.request.Request(
                base + "/api/auth/login",
                data=json.dumps({
                    "username": "demo-viewer",
                    "password": DEMO_SEED_PASSWORDS["demo-viewer"],
                }).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(login, timeout=5) as resp:
                token = json.loads(resp.read())["session_token"]
            req = urllib.request.Request(
                base + "/api/member/archive/arc-central-wrestling/playback",
                data=b"{}",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token,
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
                cookie = resp.headers.get("Set-Cookie") or ""
            self.assertNotIn("lease_token", body)
            self.assertTrue(body["allow"])
            self.assertEqual(body["media_url"], "/demo/media/evt_mw_wrestling.mp4")
            self.assertIn("tz_lease_evt_mw_wrestling=", cookie)
            self.assertIn("HttpOnly", cookie)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_public_catalog_endpoints_do_not_require_member_auth(self):
        import json
        import threading
        import urllib.request

        from backend.http_server import make_http_server

        cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                     allowed_origins=["http://127.0.0.1"])
        httpd = make_http_server(cfg, self.cp, "/tmp")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            base = f"http://{host}:{port}"
            with urllib.request.urlopen(base + "/api/public/live", timeout=5) as resp:
                live = json.loads(resp.read())
            with urllib.request.urlopen(base + "/api/public/schedules", timeout=5) as resp:
                schedules = json.loads(resp.read())
            with urllib.request.urlopen(base + "/api/public/archives", timeout=5) as resp:
                archives = json.loads(resp.read())
            self.assertIn("events", live)
            self.assertIn("schedules", schedules)
            self.assertIn("archives", archives)
            self.assertGreaterEqual(len(live["events"]), 1)
            self.assertGreaterEqual(len(schedules["schedules"]), 1)
            self.assertGreaterEqual(len(archives["archives"]), 1)
            allowed = {"event_id", "title", "zone", "category", "status", "scheduled_start", "scoreboard"}
            for event in live["events"]:
                self.assertTrue(set(event).issubset(allowed))
                self.assertNotIn("rights", event)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_member_app_origin_is_allowed_even_when_not_listed(self):
        import json
        import threading
        import urllib.error
        import urllib.request

        from backend.http_server import make_http_server

        cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                     allowed_origins=["https://3zonesports.com"])
        httpd = make_http_server(cfg, self.cp, "/tmp")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            base = f"http://{host}:{port}"
            same_origin = urllib.request.Request(
                base + "/api/health",
                headers={"Origin": base},
            )
            with urllib.request.urlopen(same_origin, timeout=5) as resp:
                payload = json.loads(resp.read())
            self.assertEqual(payload["status"], "ok")

            pages_origin = urllib.request.Request(
                base + "/api/health",
                headers={"Origin": "http://127.0.0.1:5500"},
            )
            with urllib.request.urlopen(pages_origin, timeout=5) as resp:
                payload = json.loads(resp.read())
            self.assertEqual(payload["status"], "ok")

            blocked = urllib.request.Request(
                base + "/api/health",
                headers={"Origin": "https://evil.example"},
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(blocked, timeout=5)
            self.assertEqual(raised.exception.code, 403)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_member_portal_preserves_pending_playback_query(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "backend", "static", "portal.js"), encoding="utf-8") as handle:
            portal_js = handle.read()
        self.assertIn("new URLSearchParams(location.search || \"\")", portal_js)
        self.assertIn("clearPendingPlayback()", portal_js)
        self.assertIn("/api/member/archive/${pending.id}/playback", portal_js)
        self.assertIn("authError", portal_js)
        self.assertIn("demo-hint", portal_js)
        self.assertIn('if (result.home === "/ops"', portal_js)
        self.assertNotIn(" sessionStorage", portal_js)


class AuthHttpTests(unittest.TestCase):
    def setUp(self):
        import threading

        from backend.config import DEMO_SEED_PASSWORDS
        from backend.http_server import make_http_server

        self.DEMO_SEED_PASSWORDS = DEMO_SEED_PASSWORDS
        self.db = Database(":memory:")
        seed_if_empty(self.db)
        cfg = Config(env="demo", http_host="127.0.0.1", http_port=0,
                     allowed_origins=["http://127.0.0.1"], media_provider="fake")
        self.cp = ControlPlane(self.db, cfg)
        self.httpd = make_http_server(cfg, self.cp, "/tmp")
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    @staticmethod
    def _cookie(headers, name="tz_member_session"):
        raw = headers.get("Set-Cookie") or ""
        for part in raw.split(";"):
            piece = part.strip()
            if piece.startswith(name + "="):
                return piece.split("=", 1)[1]
        return None

    def _json(self, method, path, body=None, cookie=None, token=None):
        import json
        import urllib.error
        import urllib.request

        headers = {}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if cookie:
            headers["Cookie"] = f"tz_member_session={cookie}"
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read() or b"{}")
                return resp.status, payload, resp.headers
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read() or b"{}")
            return exc.code, payload, exc.headers

    def test_register_cookie_sees_own_account_and_can_post(self):
        status, body, headers = self._json("POST", "/api/auth/register", {
            "username": "pat-fan",
            "password": "password123",
            "display_name": "Pat Fan",
        })
        self.assertEqual(status, 200, body)
        cookie = self._cookie(headers)
        self.assertTrue(cookie)
        self.assertEqual(body["user"]["role"], "viewer")
        self.assertEqual(body["home"], "/")

        status, me, _ = self._json("GET", "/api/member/me", cookie=cookie)
        self.assertEqual(status, 200, me)
        self.assertEqual(me["member"]["display_name"], "Pat Fan")
        handle = me["member"]["username"]
        self.assertTrue(handle)
        self.assertNotIn("-", handle)

        status, upload, _ = self._json("POST", "/api/network/uploads", {"kind": "photo"}, cookie=cookie)
        self.assertEqual(status, 201, upload)
        token = upload["upload_url"].rsplit("/", 1)[-1]
        status, done, _ = self._json(
            "POST", f"/api/network/provider/fake/upload/{token}",
            {"filename": "sideline.jpg", "byte_size": 12},
        )
        self.assertEqual(status, 200, done)
        status, published, _ = self._json("POST", "/api/network/posts", {
            "upload_job_id": upload["upload_job_id"],
            "caption": "Sideline photo",
            "sport": "basketball",
            "visibility": "public",
        }, cookie=cookie)
        self.assertEqual(status, 201, published)
        self.assertEqual(published["post"]["caption"], "Sideline photo")

        status, tab, _ = self._json("GET", f"/api/network/profiles/{handle}/posts", cookie=cookie)
        self.assertEqual(status, 200, tab)
        self.assertTrue(any(item.get("post_id") == published["post"]["post_id"] for item in tab["items"]))

    def test_owner_cookie_restores_ops_and_viewer_cannot_read_inventory(self):
        status, body, headers = self._json("POST", "/api/auth/login", {
            "username": "demo-owner",
            "password": self.DEMO_SEED_PASSWORDS["demo-owner"],
        })
        self.assertEqual(status, 200, body)
        self.assertEqual(body["home"], "/ops")
        cookie = self._cookie(headers)
        status, me, _ = self._json("GET", "/api/me", cookie=cookie)
        self.assertEqual(status, 200, me)
        self.assertEqual(me["user"]["role"], "owner")
        self.assertTrue(me["session_token"])
        self.assertEqual(me["home"], "/ops")

        status, viewer, vheaders = self._json("POST", "/api/auth/login", {
            "username": "demo-viewer",
            "password": self.DEMO_SEED_PASSWORDS["demo-viewer"],
        })
        self.assertEqual(status, 200, viewer)
        vcookie = self._cookie(vheaders)
        status, inv, _ = self._json("GET", "/api/owner/inventory", cookie=vcookie)
        self.assertEqual(status, 403)
        self.assertEqual(inv["code"], "owner_required")

    def test_owner_issues_staff_who_can_open_ops(self):
        status, owner, headers = self._json("POST", "/api/auth/login", {
            "username": "demo-owner",
            "password": self.DEMO_SEED_PASSWORDS["demo-owner"],
        })
        self.assertEqual(status, 200, owner)
        cookie = self._cookie(headers)
        status, issued, _ = self._json("POST", "/api/owner/staff", {
            "username": "andre-ops",
            "password": "password123",
            "display_name": "Andre",
            "role": "owner",
        }, cookie=cookie)
        self.assertEqual(status, 201, issued)
        self.assertEqual(issued["user"]["role"], "owner")

        status, login, _ = self._json("POST", "/api/auth/login", {
            "username": "andre-ops",
            "password": "password123",
        })
        self.assertEqual(status, 200, login)
        self.assertEqual(login["home"], "/ops")
        self.assertEqual(login["user"]["role"], "owner")

        status, reserved, _ = self._json("POST", "/api/auth/register", {
            "username": "demo-owner",
            "password": "password123",
            "display_name": "Nope",
        })
        self.assertEqual(status, 400)
        self.assertEqual(reserved["code"], "bad_username")


if __name__ == "__main__":
    unittest.main()
