import asyncio
import base64
import hashlib
import hmac
import io
import json
import os
import unittest
import zipfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bcrypt
import httpx
from pydantic import ValidationError
from bson import ObjectId

import main


async def api_request(method: str, path: str, **kwargs):
    headers = kwargs.setdefault("headers", {})
    headers.setdefault("Origin", main.FRONTEND_URL)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


class SecurityHelpersTest(unittest.TestCase):
    def test_jwt_duration_is_parsed_and_bounded(self):
        self.assertEqual(main.parse_duration_seconds("30m"), 1800)
        self.assertEqual(main.parse_duration_seconds("8h"), 28800)
        self.assertEqual(main.parse_duration_seconds("1d"), 86400)
        for value in ("0h", "forever", "31d"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                main.parse_duration_seconds(value)

    def test_production_origins_require_https_and_reject_wildcards(self):
        self.assertEqual(
            main.validate_https_origin("https://www.example.com", "FRONTEND_URL"),
            "https://www.example.com",
        )
        for value in (
            "http://www.example.com",
            "https://*.example.com",
            "https://www.example.com/admin",
            "https://user:pass@example.com",
        ):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                main.validate_https_origin(value, "FRONTEND_URL")

    def test_production_cors_uses_only_explicit_frontend_origins(self):
        with (
            patch.object(main, "PRODUCTION", True),
            patch.object(main, "FRONTEND_URL", "https://www.example.com"),
            patch.object(main, "API_ALLOWED_ORIGINS", "https://example.com, https://admin.example.com"),
            patch.dict(os.environ, {"CLIENT_ORIGIN": "http://localhost:3000"}),
        ):
            self.assertEqual(
                main.configured_origins(),
                {"https://www.example.com", "https://example.com", "https://admin.example.com"},
            )

    def test_production_requires_distinct_encryption_and_index_secrets(self):
        values = {
            "ADMIN_EMAIL": "admin@example.com",
            "ADMIN_PASSWORD": "secure-production-admin-password",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_FROM": "portfolio@example.com",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
        }
        with (
            patch.object(main, "PRODUCTION", True),
            patch.object(main, "DB_NAME", "portfolio"),
            patch.object(main, "MONGODB_URI", "mongodb+srv://cluster.example.com/portfolio"),
            patch.object(main, "API_PUBLIC_URL", "https://api.example.com"),
            patch.object(main, "FRONTEND_URL", "https://www.example.com"),
            patch.object(main, "WEBSITE_URL", "https://www.example.com"),
            patch.object(main, "JWT_SECRET", "test-production-jwt-secret-abcdefghijklmnopqrstuvwxyz"),
            patch.object(main, "encryption_seed", "test-production-data-encryption-secret-abcdefghijklmnopqrstuvwxyz"),
            patch.object(main, "email_index_seed", "test-production-email-index-secret-abcdefghijklmnopqrstuvwxyz"),
            patch.dict(os.environ, values, clear=False),
        ):
            main.validate_production_config()
            with patch.object(main, "email_index_seed", main.JWT_SECRET):
                with self.assertRaisesRegex(RuntimeError, "must be different secrets"):
                    main.validate_production_config()
            with patch.dict(os.environ, {"ADMIN_PASSWORD": "replace-with-a-unique-password-of-at-least-12-characters"}):
                with self.assertRaisesRegex(RuntimeError, "ADMIN_PASSWORD"):
                    main.validate_production_config()

    def test_mongodb_tls_detection_requires_tls_enabled(self):
        self.assertTrue(main.mongo_uri_uses_tls("mongodb+srv://cluster.example.com/db"))
        self.assertFalse(main.mongo_uri_uses_tls("mongodb+srv://cluster.example.com/db?tls=false"))
        self.assertTrue(main.mongo_uri_uses_tls("mongodb://cluster.example.com/db?tls=true"))
        self.assertTrue(main.mongo_uri_uses_tls("mongodb://cluster.example.com/db?ssl=1"))
        self.assertFalse(main.mongo_uri_uses_tls("mongodb://localhost/db"))
        self.assertFalse(main.mongo_uri_uses_tls("mongodb://cluster.example.com/db?tls=false"))
        self.assertFalse(main.mongo_uri_uses_tls("https://cluster.example.com/db?tls=true"))

    def test_request_size_limit_rejects_chunked_oversize_body(self):
        async def receive():
            return {"type": "http.request", "body": b"1234", "more_body": False}

        async def send(message):
            messages.append(message)

        async def consume_body(scope, wrapped_receive, wrapped_send):
            await wrapped_receive()
            await main.Response(status_code=204)(scope, wrapped_receive, wrapped_send)

        async def run():
            middleware = main.RequestSizeLimitMiddleware(consume_body, maximum_bytes=3)
            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/test",
                "raw_path": b"/test",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
            }
            await middleware(scope, receive, send)

        messages = []
        asyncio.run(run())
        response_start = next(message for message in messages if message["type"] == "http.response.start")
        self.assertEqual(response_start["status"], 413)

    def test_health_endpoints_report_liveness_and_database_readiness(self):
        async def run():
            self.assertEqual(await main.health_liveness(), {"status": "ok"})
            with patch.object(main, "check_database_connection", new=AsyncMock()):
                self.assertEqual(await main.health_readiness(), {"status": "ready"})
            with patch.object(main, "check_database_connection", new=AsyncMock(side_effect=main.PyMongoError("offline"))):
                with self.assertRaises(main.HTTPException) as raised:
                    await main.health_readiness()
                self.assertEqual(raised.exception.status_code, 503)

        asyncio.run(run())

    def test_login_no_longer_accepts_authenticator_codes(self):
        base = {"email": "admin@example.com", "password": "valid-password"}
        with self.assertRaises(ValidationError):
            main.LoginInput(**base, otp="123456")

    def test_staff_roles_do_not_include_two_factor_permissions(self):
        for role in main.VALID_ROLES:
            if role == "admin":
                self.assertIn("*", main.ROLE_PERMISSIONS[role])
            else:
                self.assertNotIn("security:manage", main.ROLE_PERMISSIONS[role])

    def test_unconfigured_origins_are_not_trusted(self):
        self.assertNotIn("", main.frontend_origins())

    def test_media_records_require_https_and_valid_categories(self):
        main.validate_media({"title": "Cover", "url": "https://images.example.com/cover.jpg", "category": "book-cover"})
        main.validate_media({"title": "Gallery", "url": "https://images.example.com/gallery.jpg", "category": "gallery", "public": True})
        for value in ("http://images.example.com/cover.jpg", "javascript:alert(1)", "https://user:pass@images.example.com/cover.jpg", "https://[broken"):
            with self.subTest(value=value), self.assertRaises(main.HTTPException):
                main.validate_media({"url": value})
        with self.assertRaises(main.HTTPException):
            main.validate_media({"category": "executable"})
        with self.assertRaises(main.HTTPException):
            main.validate_media({"public": "yes"})

    def test_team_roles_have_portfolio_permissions_without_commerce_permissions(self):
        self.assertIn("analytics:read", main.ROLE_PERMISSIONS["manager"])
        self.assertIn("media:write", main.ROLE_PERMISSIONS["editor"])
        for role in ("admin", "manager", "editor", "support"):
            permissions = main.ROLE_PERMISSIONS[role]
            self.assertFalse(any(permission.startswith(("orders:", "payments:", "customers:", "reviews:")) for permission in permissions))

    def test_book_fields_support_store_inventory_and_prices(self):
        self.assertTrue({"title", "priceNpr", "stock", "category"} <= main.BOOK_FIELDS)
        with self.assertRaises(main.HTTPException):
            main.validate_resource_fields({"title": "A book", "price": 10}, main.BOOK_FIELDS)
        main.validate_book({"priceNpr": 450.5, "stock": 10, "category": "Fiction"})
        for invalid in (
            {"priceNpr": 0},
            {"priceNpr": float("inf")},
            {"stock": -1},
            {"stock": 1.5},
            {"category": ""},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(main.HTTPException):
                main.validate_book(invalid)

    def test_store_bank_details_are_encrypted_before_persistence(self):
        stored = main.encrypt_fields({
            "bankAccountNumber": "1234567890",
            "contactEmail": "store@example.com",
            "address": "123 Reader Lane",
            "phone": "+9779800000000",
        })
        self.assertNotEqual(stored["bankAccountNumber"], "1234567890")
        self.assertNotEqual(stored["contactEmail"], "store@example.com")
        self.assertNotEqual(stored["address"], "123 Reader Lane")
        self.assertNotEqual(stored["phone"], "+9779800000000")
        self.assertEqual(main.serialize(stored), {
            "bankAccountNumber": "1234567890",
            "contactEmail": "store@example.com",
            "address": "123 Reader Lane",
            "phone": "+9779800000000",
        })

    def test_published_content_validates_seo_and_social_urls(self):
        main.validate_public_content("site-settings", {
            "siteTitle": "Author portfolio",
            "seoTitle": "Author — Novels and essays",
            "seoDescription": "Published works and writing.",
            "ogImage": "https://images.example.com/author.jpg",
        })
        main.validate_public_content("author-profile", {
            "name": "Author Name",
            "instagram": "https://instagram.com/author",
            "linkedin": "https://linkedin.com/in/author",
        })
        for value in (
            {"seoDescription": "x" * 321},
            {"ogImage": "javascript:alert(1)"},
            {"unexpected": "field"},
            ["not", "an", "object"],
        ):
            with self.subTest(value=value), self.assertRaises(main.HTTPException):
                main.validate_public_content("site-settings", value)

    def test_published_work_status_is_validated(self):
        main.validate_book({"status": "published"})
        main.validate_book({"status": "draft"})
        with self.assertRaises(main.HTTPException):
            main.validate_book({"status": "available"})

    def test_encrypted_fields_round_trip_and_are_idempotent(self):
        stored = main.encrypt_text("reader@example.com")
        self.assertNotEqual(stored, "reader@example.com")
        self.assertEqual(main.decrypt_text(stored), "reader@example.com")
        self.assertEqual(main.encrypt_text(stored), stored)

    def test_serialized_user_records_exclude_passwords_and_otp_challenges(self):
        record = main.serialize({
            "passwordHash": "password-hash",
            "adminLoginOtpHash": "otp-hash",
            "adminLoginOtpExpiresAt": main.now_utc(),
            "adminEmailOtpHash": "verification-hash",
            "adminPasswordResetOtpHash": "reset-hash",
        })
        self.assertEqual(record, {})

    def test_password_hashing_upgrades_legacy_bcrypt(self):
        password = "A sufficiently long test password!"
        old_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        verified, upgraded = main.PASSWORD_HASHER.verify_and_update(password, old_hash)
        self.assertTrue(verified)
        self.assertIsNotNone(upgraded)
        self.assertTrue(upgraded.startswith("$argon2"))

    def test_otp_is_bound_to_email_and_expiry(self):
        email = "reader@example.com"
        code = "123456"
        digest, expires = main.issue_otp(email, "verify", code)
        self.assertTrue(main.otp_matches(email, "verify", code, digest, expires))
        self.assertFalse(main.otp_matches(email, "verify", "654321", digest, main.now_utc() + timedelta(minutes=1)))
        self.assertFalse(main.otp_matches(email, "verify", code, digest, main.now_utc() - timedelta(seconds=1)))

    def test_admin_auth_routes_are_rate_limited(self):
        async def pass_through(scope, receive, send):
            await main.Response(status_code=204)(scope, receive, send)

        async def requests():
            limiter = main.RateLimitMiddleware(pass_through)
            transport = httpx.ASGITransport(app=limiter)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                responses = [
                    await client.post("/api/admin/auth/password/request")
                    for _ in range(13)
                ]
                return responses

        responses = asyncio.run(requests())
        self.assertEqual(responses[-1].status_code, 429)
        self.assertIn("Retry-After", responses[-1].headers)

    def test_api_rate_limits_are_isolated_per_route(self):
        async def pass_through(scope, receive, send):
            await main.Response(status_code=204)(scope, receive, send)

        async def requests():
            limiter = main.RateLimitMiddleware(pass_through)
            transport = httpx.ASGITransport(app=limiter)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                responses = [await client.get("/api/books") for _ in range(151)]
                other_route = await client.get("/api/gallery")
                return responses, other_route

        responses, other_route = asyncio.run(requests())
        self.assertEqual(responses[-2].status_code, 204)
        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(other_route.status_code, 204)

    def test_unknown_api_paths_share_a_bounded_rate_limit_bucket(self):
        async def pass_through(scope, receive, send):
            await main.Response(status_code=204)(scope, receive, send)

        async def requests():
            limiter = main.RateLimitMiddleware(pass_through)
            transport = httpx.ASGITransport(app=limiter)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                first = await client.get("/api/unknown-one")
                second = await client.get("/api/unknown-two")
                return first, second, limiter.events

        first, second, buckets = asyncio.run(requests())
        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        self.assertEqual(len(buckets), 1)

    def test_khalti_statuses_and_order_binding(self):
        completed = main.validate_khalti_lookup(
            {"pidx": "pidx-1", "total_amount": 1250, "status": "Completed"},
            200,
            "pidx-1",
            12.5,
        )
        self.assertEqual(completed["status"], "Completed")
        expired = main.validate_khalti_lookup(
            {"pidx": "pidx-2", "total_amount": 2500, "status": "Expired"},
            400,
            "pidx-2",
            25,
        )
        self.assertEqual(expired["status"], "Expired")
        with self.assertRaises(main.HTTPException):
            main.validate_khalti_lookup(
                {"pidx": "unexpected", "total_amount": 1250, "status": "Completed"},
                200,
                "pidx-1",
                12.5,
            )

    def test_esewa_amount_and_signed_callback(self):
        self.assertTrue(main.esewa_amount_matches("1,000.0", 1000))
        self.assertFalse(main.esewa_amount_matches("999.99", 1000))
        previous = os.environ.get("ESEWA_TEST_SECRET_KEY")
        os.environ["ESEWA_TEST_SECRET_KEY"] = "test-secret"
        try:
            order_id = ObjectId()
            signed_fields = "total_amount,transaction_uuid,product_code"
            payload = {
                "total_amount": "100.00",
                "transaction_uuid": str(order_id),
                "product_code": "EPAYTEST",
                "signed_field_names": signed_fields,
            }
            message = ",".join(f"{key}={payload[key]}" for key in signed_fields.split(","))
            payload["signature"] = base64.b64encode(
                hmac.new(b"test-secret", message.encode(), hashlib.sha256).digest()
            ).decode()
            encoded = base64.b64encode(json.dumps(payload).encode()).decode()
            verified = main.verify_esewa_callback(encoded, {"_id": order_id, "paymentMode": "test"})
            self.assertEqual(verified["transaction_uuid"], str(order_id))
            payload["signature"] = "invalid"
            encoded = base64.b64encode(json.dumps(payload).encode()).decode()
            with self.assertRaises(main.HTTPException):
                main.verify_esewa_callback(encoded, {"_id": order_id, "paymentMode": "test"})
        finally:
            if previous is None:
                os.environ.pop("ESEWA_TEST_SECRET_KEY", None)
            else:
                os.environ["ESEWA_TEST_SECRET_KEY"] = previous


class ApiContractTest(unittest.TestCase):
    def setUp(self):
        configured_email = patch.dict(os.environ, {"ADMIN_EMAIL": "admin@example.com"})
        configured_email.start()
        self.addCleanup(configured_email.stop)

    def test_public_read_endpoints_return_expected_shapes(self):
        class EmptyCursor:
            def sort(self, *_args):
                return self

            def limit(self, *_args):
                return self

            async def to_list(self, _length):
                return []

        class EmptyCollection:
            def find(self, *_args):
                return EmptyCursor()

        class EmptyDatabase:
            def __init__(self):
                self.books = EmptyCollection()
                self.collections = {
                    main.MEDIA_COLLECTION: EmptyCollection(),
                    main.CONTENT_COLLECTION: EmptyCollection(),
                }

            def __getitem__(self, collection_name):
                return self.collections[collection_name]

        async def requests():
            with patch.object(main, "db", EmptyDatabase()):
                return await asyncio.gather(
                    api_request("GET", "/api/books"),
                    api_request("GET", "/api/gallery"),
                    api_request("GET", "/api/content"),
                )

        responses = asyncio.run(requests())
        self.assertEqual([response.status_code for response in responses], [200] * 3)
        self.assertEqual([response.json() for response in responses], [
            {"books": []},
            {"images": []},
            {"content": []},
        ])
        # Public catalogue reads are revalidated on every request rather than never stored.
        self.assertTrue(all(response.headers["cache-control"] == "no-cache" for response in responses))
        self.assertTrue(all(response.headers["etag"].startswith('W/"') for response in responses))

    def test_unchanged_public_reads_revalidate_with_304_and_private_routes_stay_uncached(self):
        class ContentCursor:
            def __init__(self, rows):
                self.rows = rows

            async def to_list(self, _length):
                return self.rows

        rows = [{"key": "author-profile", "value": {"bio": "x" * 3000}}]
        content = SimpleNamespace(find=lambda *_args: ContentCursor(rows))

        async def requests():
            with patch.object(main, "db", {main.CONTENT_COLLECTION: content}):
                first = await api_request("GET", "/api/content", headers={"Accept-Encoding": "gzip"})
                repeat = await api_request("GET", "/api/content", headers={"If-None-Match": first.headers["etag"]})
                rows[0]["value"]["bio"] = "changed"
                changed = await api_request("GET", "/api/content", headers={"If-None-Match": first.headers["etag"]})
                private = await api_request("GET", "/api/auth/me")
            return first, repeat, changed, private

        first, repeat, changed, private = asyncio.run(requests())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["content-encoding"], "gzip")
        self.assertEqual(first.json()["content"][0]["value"]["bio"], "x" * 3000)
        self.assertEqual(repeat.status_code, 304)
        self.assertEqual(repeat.content, b"")
        self.assertEqual(repeat.headers["etag"], first.headers["etag"])
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.headers["etag"], first.headers["etag"])
        self.assertEqual(private.headers["cache-control"], "no-store")
        self.assertNotIn("etag", private.headers)

    def test_newsletter_signup_stores_an_encrypted_normalized_email_and_is_idempotent(self):
        subscriptions = SimpleNamespace(
            update_one=AsyncMock(side_effect=[None, main.DuplicateKeyError("duplicate")])
        )

        class NewsletterDatabase:
            def __getitem__(self, collection_name):
                if collection_name != main.NEWSLETTER_COLLECTION:
                    raise AssertionError(f"Unexpected collection: {collection_name}")
                return subscriptions

        async def requests():
            with patch.object(main, "db", NewsletterDatabase()):
                return await asyncio.gather(*(
                    api_request("POST", "/api/newsletter/subscribe", json={"email": " Reader@Example.com "}),
                    api_request("POST", "/api/newsletter/subscribe", json={"email": "reader@example.com"}),
                ))

        responses = asyncio.run(requests())
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(responses[0].json(), {"subscribed": True, "message": "Thanks for subscribing."})
        update = subscriptions.update_one.await_args_list[0].args[1]
        self.assertEqual(
            subscriptions.update_one.await_args_list[0].args[0],
            {"emailHash": main.email_index("reader@example.com")},
        )
        self.assertEqual(main.decrypt_text(update["$setOnInsert"]["email"]), "reader@example.com")
        self.assertEqual(update["$setOnInsert"]["emailHash"], main.email_index("reader@example.com"))
        self.assertTrue(all(response.json() == responses[0].json() for response in responses))

    def test_newsletter_signup_rejects_untrusted_origins_and_invalid_emails(self):
        async def requests():
            return await asyncio.gather(
                api_request(
                    "POST",
                    "/api/newsletter/subscribe",
                    json={"email": "reader@example.com"},
                    headers={"Origin": "https://attacker.example"},
                ),
                api_request("POST", "/api/newsletter/subscribe", json={"email": "not-an-email"}),
            )

        responses = asyncio.run(requests())
        self.assertEqual([response.status_code for response in responses], [403, 422])

    def test_customer_auth_api_routes_are_removed(self):
        paths = {
            "/api/customer/auth/code/request",
            "/api/customer/auth/code/verify",
            "/api/customer/auth/me",
            "/api/customer/auth/logout",
        }
        registered_paths = {getattr(route, "path", "") for route in main.app.routes}
        self.assertTrue(paths.isdisjoint(registered_paths))

    def test_journal_api_routes_are_removed(self):
        async def requests():
            return await asyncio.gather(
                api_request("GET", "/api/blog"),
                api_request("GET", "/api/admin/blogs"),
            )

        responses = asyncio.run(requests())
        self.assertEqual([response.status_code for response in responses], [404, 404])

    def test_all_admin_management_routes_require_a_session(self):
        public_auth_paths = {
            "/api/admin/auth/login",
            "/api/admin/auth/email/request",
            "/api/admin/auth/email/verify",
            "/api/admin/auth/password/request",
            "/api/admin/auth/password/reset",
            "/api/admin/auth/logout",
        }
        protected = []
        for route in main.app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            if not path.startswith("/api/admin/") or path in public_auth_paths:
                continue
            method = next((candidate for candidate in ("GET", "POST", "PUT", "PATCH", "DELETE") if candidate in methods), None)
            if method:
                protected.append((method, path))

        async def requests():
            responses = []
            for method, path in protected:
                path = path.replace("{user_id}", str(ObjectId())).replace("{item_id}", str(ObjectId()))
                path = path.replace("{key}", "test-key")
                body = {"code": "123456"}
                if path.endswith("/auth/2fa/disable"):
                    body = {"email": "admin@example.com", "password": "valid-password", "otp": "123456"}
                response = await api_request(
                    method,
                    path,
                    **({"json": body} if method in {"POST", "PUT", "PATCH"} else {}),
                )
                responses.append((method, path, response.status_code))
            return responses

        responses = asyncio.run(requests())
        self.assertTrue(protected)
        self.assertTrue(
            all(status == 401 for _, _, status in responses),
            msg=f"Admin endpoints without a session returned unexpected results: {responses}",
        )

    def test_admin_login_rejects_untrusted_origins(self):
        async def request():
            with (
                patch.dict(os.environ, {"ADMIN_EMAIL": "admin@example.com"}),
                patch.object(main, "find_user_by_email", new=AsyncMock()) as find_user,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/login",
                    json={"email": "admin@example.com", "password": "secure test password"},
                    headers={"Origin": "https://attacker.example"},
                )
                return response, find_user

        response, find_user = asyncio.run(request())
        self.assertEqual(response.status_code, 403)
        find_user.assert_not_awaited()

    def test_admin_login_rejects_emails_outside_configured_allowlist(self):
        async def request():
            with (
                patch.dict(os.environ, {"ADMIN_EMAIL": "admin@example.com"}),
                patch.object(main, "find_user_by_email", new=AsyncMock()) as find_user,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/login",
                    json={"email": "other@example.com", "password": "secure test password"},
                    headers={"Origin": main.FRONTEND_URL},
                )
                return response, find_user

        response, find_user = asyncio.run(request())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Email or password is incorrect."})
        find_user.assert_not_awaited()

    def test_existing_admin_sessions_are_rejected_for_other_emails(self):
        user = {
            "_id": ObjectId(),
            "email": "other@example.com",
            "role": "admin",
            "active": True,
            "authVersion": 0,
        }
        jti = "test-admin-session"
        token = main.jwt.encode(
            {
                "sub": str(user["_id"]),
                "role": "admin",
                "version": 0,
                "jti": jti,
                "exp": int((main.now_utc() + timedelta(minutes=5)).timestamp()),
            },
            main.JWT_SECRET,
            algorithm="HS256",
        )
        database = SimpleNamespace(
            auth_sessions=SimpleNamespace(
                find_one=AsyncMock(return_value={
                    "kind": "admin-setup",
                    "expiresAt": main.now_utc() + timedelta(minutes=5),
                })
            ),
            users=SimpleNamespace(find_one=AsyncMock(return_value=user)),
        )

        async def request():
            with (
                patch.dict(os.environ, {"ADMIN_EMAIL": "admin@example.com"}),
                patch.object(main, "db", database),
            ):
                return await api_request(
                    "GET",
                    "/api/admin/auth/me",
                    headers={"Cookie": f"store_admin={token}"},
                )

        response = asyncio.run(request())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"error": "This account is not authorized for the Admin Panel."},
        )

    def test_admin_sign_in_uses_bootstrap_email_and_password_without_email_otp(self):
        email = "admin@example.com"
        password = "secure test password"
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "passwordHash": main.PASSWORD_HASHER.hash(password),
            "role": "admin",
            "active": True,
            "emailVerified": True,
        }

        async def request():
            async def create_admin_session(user, response, *, admin=False):
                response.set_cookie("store_admin", "test-session", httponly=True)
                return {"email": email, "role": user["role"], "permissions": ["*"]}

            with (
                patch.dict(os.environ, {"ADMIN_EMAIL": email}),
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(main, "create_session", new=AsyncMock(side_effect=create_admin_session)) as create_session,
                patch.object(main, "audit", new=AsyncMock()) as audit,
                patch.object(main, "send_email_code", new=AsyncMock()) as send_code,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/login",
                    json={"email": email, "password": password},
                    headers={"Origin": main.FRONTEND_URL},
                )
                return response, create_session, audit, send_code

        response, create_session, audit, send_code = asyncio.run(request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["role"], "admin")
        self.assertNotIn("requiresTwoFactorSetup", response.json())
        self.assertIn("store_admin=", response.headers.get("set-cookie", ""))
        create_session.assert_awaited_once()
        self.assertTrue(create_session.await_args.kwargs["admin"])
        audit.assert_awaited_once()
        send_code.assert_not_awaited()

    def test_admin_password_rejects_an_invalid_stored_hash_without_server_error(self):
        email = "admin@example.com"
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "passwordHash": "invalid-password-hash",
            "role": "admin",
            "active": True,
            "emailVerified": True,
        }

        async def request():
            with (
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(main, "send_email_code", new=AsyncMock()) as send_code,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/login",
                    json={"email": email, "password": "any-password"},
                )
                return response, send_code

        response, send_code = asyncio.run(request())
        self.assertEqual(response.status_code, 401)
        send_code.assert_not_awaited()

    def test_admin_sign_in_requires_verified_email(self):
        email = "admin@example.com"
        password = "secure test password"
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "passwordHash": main.PASSWORD_HASHER.hash(password),
            "role": "admin",
            "active": True,
            "emailVerified": False,
        }

        async def request():
            with (
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(main, "create_session", new=AsyncMock()) as create_session,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/login",
                    json={"email": email, "password": password},
                )
                return response, create_session

        response, create_session = asyncio.run(request())
        self.assertEqual(response.status_code, 403)
        self.assertIn("verify your email", response.json()["error"].lower())
        create_session.assert_not_awaited()

    def test_password_reset_request_sends_a_generic_email_code_response(self):
        email = "admin@example.com"
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "role": "admin",
            "active": True,
        }

        async def request():
            with (
                patch.dict(os.environ, {"SMTP_HOST": "smtp.example.test", "SMTP_FROM": "admin@example.com"}),
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(
                    main,
                    "db",
                    SimpleNamespace(users=SimpleNamespace(update_one=AsyncMock())),
                ) as database,
                patch.object(main, "send_email_code", new=AsyncMock()) as send_code,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/password/request",
                    json={"email": email},
                )
                return response, database.users.update_one, send_code

        response, update_user, send_code = asyncio.run(request())
        self.assertEqual(response.status_code, 200)
        self.assertIn("If an active admin account matches", response.json()["message"])
        self.assertEqual(send_code.await_args.args[2], "admin-password-reset")
        code = send_code.await_args.args[1]
        fields = update_user.await_args.args[1]["$set"]
        self.assertTrue(main.otp_matches(
            email,
            "admin-password-reset",
            code,
            fields["adminPasswordResetOtpHash"],
            fields["adminPasswordResetOtpExpiresAt"],
        ))

    def test_password_reset_reports_missing_mail_relay_configuration(self):
        async def request():
            with patch.dict(os.environ, {"SMTP_HOST": "", "SMTP_FROM": ""}):
                return await api_request(
                    "POST",
                    "/api/admin/auth/password/request",
                    json={"email": "admin@example.com"},
                )

        response = asyncio.run(request())
        self.assertEqual(response.status_code, 503)
        self.assertIn("email delivery is not configured", response.json()["error"].lower())

    def test_bootstrap_email_change_requires_reverification_and_revokes_sessions(self):
        old_email = "old-admin@example.com"
        new_email = "new-admin@example.com"
        user = {
            "_id": ObjectId(),
            "email": main.encrypt_text(old_email),
            "emailHash": main.email_index(old_email),
            "role": "admin",
            "authVersion": 3,
        }
        users = SimpleNamespace(
            find_one=AsyncMock(return_value=user),
            update_one=AsyncMock(),
        )
        metadata = SimpleNamespace(
            find_one=AsyncMock(return_value={"user": user["_id"]}),
            update_one=AsyncMock(),
        )
        sessions = SimpleNamespace(delete_many=AsyncMock())
        database = SimpleNamespace(app_metadata=metadata, users=users, auth_sessions=sessions)

        async def bootstrap():
            with (
                patch.dict(os.environ, {"ADMIN_EMAIL": new_email, "ADMIN_PASSWORD": "secure bootstrap password"}),
                patch.object(main, "db", database),
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=None)),
            ):
                await main.bootstrap_admin()

        asyncio.run(bootstrap())
        update = users.update_one.await_args.args[1]
        self.assertEqual(main.decrypt_text(update["$set"]["email"]), new_email)
        self.assertFalse(update["$set"]["emailVerified"])
        self.assertEqual(update["$set"]["authVersion"], 4)
        self.assertIn("adminEmailOtpHash", update["$unset"])
        sessions.delete_many.assert_awaited_once_with({"user": user["_id"]})
        metadata.update_one.assert_awaited_once()

    def test_admin_sign_in_ignores_legacy_two_factor_data(self):
        email = "admin@example.com"
        password = "secure test password"
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "passwordHash": main.PASSWORD_HASHER.hash(password),
            "role": "admin",
            "active": True,
            "emailVerified": True,
            "twoFactorEnabled": True,
            "totpSecret": "legacy-secret",
        }

        async def requests():
            async def create_admin_session(user, response, *, admin=False):
                response.set_cookie("store_admin", "test-session", httponly=True)
                return {"email": email, "role": user["role"], "permissions": ["*"]}

            with (
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(main, "create_session", new=AsyncMock(side_effect=create_admin_session)) as create_session,
                patch.object(main, "audit", new=AsyncMock()),
            ):
                password_only = await api_request(
                    "POST",
                    "/api/admin/auth/login",
                    json={"email": email, "password": password},
                )
                authenticator_field = await api_request(
                    "POST",
                    "/api/admin/auth/login",
                    json={"email": email, "password": password, "otp": "123456"},
                )
                return password_only, authenticator_field, create_session

        password_only, authenticator_field, create_session = asyncio.run(requests())
        self.assertEqual(password_only.status_code, 200)
        self.assertEqual(authenticator_field.status_code, 422)
        create_session.assert_awaited_once()

    def test_admin_email_verification_sends_a_code_that_can_be_verified(self):
        email = "admin@example.com"
        password = "secure test password"
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "passwordHash": main.PASSWORD_HASHER.hash(password),
            "role": "admin",
            "active": True,
            "emailVerified": False,
        }

        async def requests():
            with (
                patch.dict(os.environ, {"SMTP_HOST": "smtp.example.test", "SMTP_FROM": "admin@example.com"}),
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(main, "db", SimpleNamespace(users=SimpleNamespace(update_one=AsyncMock()))) as database,
                patch.object(main, "send_email_code", new=AsyncMock()) as send_code,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/email/request",
                    json={"email": email, "password": password},
                )
                return response, database.users.update_one, send_code

        response, update_user, send_code = asyncio.run(requests())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(send_code.await_args.args[0], email)
        code = send_code.await_args.args[1]
        self.assertEqual(send_code.await_args.args[2], "admin-verify")
        otp_fields = update_user.await_args.args[1]["$set"]
        self.assertTrue(main.otp_matches(
            email,
            "admin-verify",
            code,
            otp_fields["adminEmailOtpHash"],
            otp_fields["adminEmailOtpExpiresAt"],
        ))

    def test_admin_email_verification_explains_missing_smtp_configuration(self):
        email = "admin@example.com"
        password = "secure test password"
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "passwordHash": main.PASSWORD_HASHER.hash(password),
            "role": "admin",
            "active": True,
            "emailVerified": False,
        }

        async def request():
            with (
                patch.dict(os.environ, {"SMTP_HOST": "", "SMTP_FROM": ""}),
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(main, "send_email_code", wraps=main.send_email_code) as send_code,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/email/request",
                    json={"email": email, "password": password},
                )
                return response, send_code

        response, send_code = asyncio.run(request())
        self.assertEqual(response.status_code, 503)
        self.assertIn("SMTP_HOST and SMTP_FROM", response.json()["error"])
        self.assertIn("restart the API", response.json()["error"])
        send_code.assert_awaited_once()

    def test_smtp_authentication_requires_username_and_password_together(self):
        async def request():
            with (
                patch.dict(os.environ, {
                    "SMTP_HOST": "smtp-relay.example.test",
                    "SMTP_FROM": "admin@example.com",
                    "SMTP_USERNAME": "admin@example.com",
                    "SMTP_PASSWORD": "",
                }),
            ):
                return await main.send_email_code(
                    "admin@example.com",
                    "123456",
                    "admin-verify",
                )

        with self.assertRaises(main.HTTPException) as raised:
            asyncio.run(request())
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("SMTP_USERNAME and SMTP_PASSWORD", raised.exception.detail)

    def test_smtp_server_disconnect_during_authentication_has_actionable_error(self):
        class DisconnectingSMTP:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def starttls(self):
                return None

            def login(self, _username, _password):
                raise main.smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

        async def run_in_thread(function):
            return function()

        async def request():
            with (
                patch.dict(os.environ, {
                    "SMTP_HOST": "smtp-relay.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_USERNAME": "admin@example.com",
                    "SMTP_PASSWORD": "test-secret",
                }),
                patch.object(main.smtplib, "SMTP", return_value=DisconnectingSMTP()),
                patch.object(main.asyncio, "to_thread", new=run_in_thread),
            ):
                return await main.send_email_code(
                    "admin@example.com",
                    "123456",
                    "admin-verify",
                )

        with self.assertRaises(main.HTTPException) as raised:
            asyncio.run(request())
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("closed the connection during authentication", raised.exception.detail)
        self.assertIn("consumer Gmail", raised.exception.detail)
        self.assertIn("App Password", raised.exception.detail)
        self.assertIn("Workspace relay", raised.exception.detail)
        self.assertIn("public IP", raised.exception.detail)

    def test_smtp_sender_rejection_has_workspace_policy_guidance(self):
        class RejectingSMTP:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def starttls(self):
                return None

            def login(self, _username, _password):
                return None

            def send_message(self, _message):
                raise main.smtplib.SMTPSenderRefused(
                    550,
                    b"5.7.0 Mail relay denied",
                    "admin@example.com",
                )

        async def run_in_thread(function):
            return function()

        async def request():
            with (
                patch.dict(os.environ, {
                    "SMTP_HOST": "smtp-relay.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_FROM": "admin@example.com",
                    "SMTP_USERNAME": "admin@example.com",
                    "SMTP_PASSWORD": "test-secret",
                }),
                patch.object(main.smtplib, "SMTP", return_value=RejectingSMTP()),
                patch.object(main.asyncio, "to_thread", new=run_in_thread),
            ):
                return await main.send_email_code(
                    "admin@example.com",
                    "123456",
                    "admin-verify",
                )

        with self.assertRaises(main.HTTPException) as raised:
            asyncio.run(request())
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("rejected the configured sender", raised.exception.detail)
        self.assertIn("Workspace SMTP relay policy", raised.exception.detail)
        self.assertIn("smtp.gmail.com", raised.exception.detail)

    def test_smtp_data_rejection_reports_provider_status(self):
        class RejectingSMTP:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def starttls(self):
                return None

            def login(self, _username, _password):
                return None

            def send_message(self, _message):
                raise main.smtplib.SMTPDataError(550, b"provider-specific response")

        async def run_in_thread(function):
            return function()

        async def request():
            with (
                patch.dict(os.environ, {
                    "SMTP_HOST": "smtp.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_FROM": "admin@example.com",
                    "SMTP_USERNAME": "admin@example.com",
                    "SMTP_PASSWORD": "test-secret",
                }),
                patch.object(main.smtplib, "SMTP", return_value=RejectingSMTP()),
                patch.object(main.asyncio, "to_thread", new=run_in_thread),
            ):
                return await main.send_email_code(
                    "admin@example.com",
                    "123456",
                    "admin-verify",
                )

        with self.assertRaises(main.HTTPException) as raised:
            asyncio.run(request())
        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("SMTP 550", raised.exception.detail)
        self.assertIn("sending restrictions", raised.exception.detail)
        self.assertNotIn("provider-specific response", raised.exception.detail)

    def test_admin_email_verification_consumes_code_once(self):
        email = "admin@example.com"
        code = "123456"
        digest, expires = main.issue_otp(email, "admin-verify", code)
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "role": "admin",
            "emailVerified": False,
            "adminEmailOtpHash": digest,
            "adminEmailOtpExpiresAt": expires,
        }

        async def request():
            with (
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(
                    main,
                    "db",
                    SimpleNamespace(users=SimpleNamespace(find_one_and_update=AsyncMock(return_value=user))),
                ) as database,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/email/verify",
                    json={"email": email, "code": code},
                )
                return response, database.users.find_one_and_update

        response, update_user = asyncio.run(request())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["verified"])
        self.assertIn("adminEmailOtpHash", update_user.await_args.args[0])

    def test_admin_password_reset_uses_email_code_and_revokes_sessions(self):
        email = "admin@example.com"
        code = "123456"
        digest, expires = main.issue_otp(email, "admin-password-reset", code)
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "role": "admin",
            "active": True,
            "adminPasswordResetOtpHash": digest,
            "adminPasswordResetOtpExpiresAt": expires,
        }

        async def request():
            with (
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(
                    main,
                    "db",
                    SimpleNamespace(
                        users=SimpleNamespace(find_one_and_update=AsyncMock(return_value=user)),
                        auth_sessions=SimpleNamespace(delete_many=AsyncMock()),
                    ),
                ) as database,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/password/reset",
                    json={"email": email, "code": code, "password": "a new secure password"},
                )
                return response, database.users.find_one_and_update, database.auth_sessions.delete_many

        response, update_user, delete_sessions = asyncio.run(request())
        self.assertEqual(response.status_code, 200)
        update = update_user.await_args.args[1]
        self.assertTrue(update["$set"]["passwordHash"].startswith("$argon2"))
        self.assertEqual(update["$inc"]["authVersion"], 1)
        self.assertIn("adminPasswordResetOtpHash", update["$unset"])
        delete_sessions.assert_awaited_once_with({"user": user["_id"]})

    def test_admin_password_reset_rejects_an_invalid_code(self):
        email = "admin@example.com"
        digest, expires = main.issue_otp(email, "admin-password-reset", "123456")
        user = {
            "_id": ObjectId(),
            "email": email,
            "emailHash": main.email_index(email),
            "role": "admin",
            "active": True,
            "adminPasswordResetOtpHash": digest,
            "adminPasswordResetOtpExpiresAt": expires,
        }

        async def request():
            with (
                patch.object(main, "find_user_by_email", new=AsyncMock(return_value=user)),
                patch.object(
                    main,
                    "db",
                    SimpleNamespace(users=SimpleNamespace(find_one_and_update=AsyncMock())),
                ) as database,
            ):
                response = await api_request(
                    "POST",
                    "/api/admin/auth/password/reset",
                    json={"email": email, "code": "654321", "password": "a new secure password"},
                )
                return response, database.users.find_one_and_update

        response, update_user = asyncio.run(request())
        self.assertEqual(response.status_code, 400)
        update_user.assert_not_awaited()

    def test_admin_requires_a_session_and_preserves_error_shape(self):
        response = asyncio.run(api_request("GET", "/api/admin/auth/me"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_api_cors_and_security_headers_are_present(self):
        async def request():
            return await api_request(
                "OPTIONS",
                "/api/books",
                headers={
                    "Origin": main.FRONTEND_URL,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "content-type",
                },
            )

        response = asyncio.run(request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], main.FRONTEND_URL)
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_admin_two_factor_routes_are_removed(self):
        routes = (
            "/api/admin/auth/2fa/enroll",
            "/api/admin/auth/2fa/confirm",
            "/api/admin/auth/2fa/disable",
            "/api/admin/auth/2fa/recovery-codes",
        )

        async def requests():
            return await asyncio.gather(*(
                api_request("POST", path, json={}) for path in routes
            ))

        responses = asyncio.run(requests())
        self.assertTrue(all(response.status_code == 404 for response in responses))

    def test_media_api_requires_an_admin_session(self):
        media = asyncio.run(api_request("GET", "/api/admin/media"))
        self.assertEqual(media.status_code, 401)

    def test_storefront_and_payment_routes_are_registered(self):
        registered = {route.path for route in main.app.routes}
        expected = {
            "/api/store/books",
            "/api/store/settings",
            "/api/orders/bank-transfer",
            "/api/payments/nepal/esewa/initiate",
            "/api/payments/nepal/khalti/initiate",
            "/api/payments/nepal/track/{order_id}",
            "/api/admin/store/analytics",
            "/api/admin/settings",
            "/api/admin/orders",
            "/api/admin/payments",
            "/api/admin/customers",
        }
        self.assertTrue(expected <= registered)

    def test_store_management_routes_require_admin_sessions(self):
        async def requests():
            reads = (
                "/api/admin/store/analytics",
                "/api/admin/settings",
                "/api/admin/orders",
                "/api/admin/payments",
                "/api/admin/customers",
            )
            responses = [api_request("GET", path) for path in reads]
            responses.append(api_request(
                "POST",
                f"/api/admin/payments/{ObjectId()}/confirm",
                json={},
            ))
            return await asyncio.gather(*responses)

        responses = asyncio.run(requests())
        self.assertEqual([response.status_code for response in responses], [401] * 6)

    def test_bookstore_upgrade_routes_are_registered(self):
        registered = {route.path for route in main.app.routes}
        expected = {
            "/api/store/books/{book_id}",
            "/api/orders/lookup",
            "/api/payments/nepal/track/{order_id}/bank-reference",
            "/api/admin/categories",
            "/api/admin/categories/{category_id}",
            "/api/admin/notifications",
            "/api/admin/notifications/read",
            "/api/admin/orders/export",
            "/api/admin/orders/{order_id}/refund",
            "/api/admin/books/{item_id}/stock",
            "/api/admin/customers/{item_id}/orders",
        }
        self.assertTrue(expected <= registered)

    def test_new_store_admin_routes_require_admin_sessions(self):
        async def requests():
            return await asyncio.gather(
                api_request("GET", "/api/admin/categories"),
                api_request("GET", "/api/admin/notifications"),
                api_request("GET", "/api/admin/orders/export"),
                api_request("GET", f"/api/admin/customers/{ObjectId()}/orders"),
                api_request("POST", f"/api/admin/books/{ObjectId()}/stock", json={"delta": 1}),
                api_request("POST", f"/api/admin/orders/{ObjectId()}/refund", json={}),
            )

        responses = asyncio.run(requests())
        self.assertEqual([response.status_code for response in responses], [401] * 6)

    def test_order_lookup_rejects_untrusted_origins(self):
        response = asyncio.run(api_request(
            "POST",
            "/api/orders/lookup",
            json={"orderId": str(ObjectId()), "email": "reader@example.com"},
            headers={"Origin": "https://attacker.example"},
        ))
        self.assertEqual(response.status_code, 403)

    def test_order_lookup_hides_whether_an_order_exists(self):
        order_id = ObjectId()
        order = {"_id": order_id, "customer": {"email": main.encrypt_text("reader@example.com")}}
        orders = SimpleNamespace(find_one=AsyncMock(side_effect=[None, order]))

        async def requests():
            with patch.object(main, "db", SimpleNamespace(orders=orders)):
                return [
                    await api_request("POST", "/api/orders/lookup", json={"orderId": str(ObjectId()), "email": "reader@example.com"}),
                    await api_request("POST", "/api/orders/lookup", json={"orderId": str(order_id), "email": "someone@example.com"}),
                ]

        missing, wrong_email = asyncio.run(requests())
        self.assertEqual((missing.status_code, wrong_email.status_code), (404, 404))
        self.assertEqual(missing.json(), wrong_email.json())
        self.assertNotIn("set-cookie", wrong_email.headers)


class CustomerAccountTest(unittest.TestCase):
    def test_customer_account_routes_are_registered(self):
        registered = {route.path for route in main.app.routes}
        expected = {
            "/api/auth/register", "/api/auth/verify-email", "/api/auth/resend-verification",
            "/api/auth/login", "/api/auth/logout", "/api/auth/me",
            "/api/auth/password/request", "/api/auth/password/reset",
            "/api/account/orders", "/api/account/profile", "/api/account/password",
            "/api/admin/accounts", "/api/admin/accounts/{account_id}",
        }
        self.assertTrue(expected <= registered)

    def test_account_routes_require_a_customer_session(self):
        async def requests():
            return await asyncio.gather(
                api_request("GET", "/api/account/orders"),
                api_request("PATCH", "/api/account/profile", json={"name": "Reader"}),
                api_request("POST", "/api/account/password", json={"currentPassword": "x", "newPassword": "y" * 12}),
                api_request("GET", "/api/admin/accounts"),
            )

        responses = asyncio.run(requests())
        self.assertEqual([response.status_code for response in responses], [401] * 4)

    def test_signed_out_visitors_get_a_null_account(self):
        self.assertEqual(asyncio.run(api_request("GET", "/api/auth/me")).json(), {"user": None})

    def test_auth_writes_reject_untrusted_origins(self):
        response = asyncio.run(api_request(
            "POST", "/api/auth/login",
            json={"email": "reader@example.com", "password": "secret"},
            headers={"Origin": "https://attacker.example"},
        ))
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_sign_in_through_the_storefront(self):
        staff = {"_id": ObjectId(), "role": "admin", "active": True, "emailVerified": True}
        with patch.object(main, "find_user_by_email", AsyncMock(return_value=staff)), patch.object(main, "create_user_login", AsyncMock()) as login:
            response = asyncio.run(api_request("POST", "/api/auth/login", json={"email": "admin@example.com", "password": "secret-password"}))
        self.assertEqual(response.status_code, 401)
        login.assert_not_awaited()

    def test_admin_sessions_are_not_customer_sessions(self):
        user_id = ObjectId()
        token = main.jwt.encode({"sub": str(user_id), "role": "admin", "version": 0, "jti": "j", "exp": main.now_utc() + timedelta(hours=1)}, main.JWT_SECRET, algorithm="HS256")
        sessions = SimpleNamespace(find_one=AsyncMock(return_value=None))
        users = SimpleNamespace(find_one=AsyncMock(return_value={"_id": user_id, "role": "admin", "active": True, "emailVerified": True}))
        request = SimpleNamespace(cookies={"store_session": token})
        with patch.object(main, "db", SimpleNamespace(auth_sessions=sessions, users=users)):
            self.assertIsNone(asyncio.run(main.customer_session(request)))
        self.assertEqual(sessions.find_one.await_args.args[0]["kind"], "user")

    def test_admin_logout_returns_no_content_and_clears_cookies(self):
        response = asyncio.run(api_request("POST", "/api/admin/auth/logout"))
        self.assertEqual(response.status_code, 204)
        cleared = " ".join(response.headers.get_list("set-cookie"))
        self.assertIn("store_admin=", cleared)
        self.assertIn("store_session=", cleared)

    def test_admin_routes_ignore_the_customer_cookie(self):
        response = asyncio.run(api_request("GET", "/api/admin/auth/me", cookies={"store_session": "not-an-admin-token"}))
        self.assertEqual(response.status_code, 401)


class MaintenanceModeTest(unittest.TestCase):
    def on(self):
        return patch.object(main, "maintenance_state", AsyncMock(return_value={"enabled": True, "message": "Back soon", "until": None, "updatedAt": None}))

    def test_public_store_api_is_closed_during_maintenance(self):
        async def requests():
            with self.on():
                return await asyncio.gather(
                    api_request("GET", "/api/store/books"),
                    api_request("GET", "/api/books"),
                    api_request("POST", "/api/orders/bank-transfer", json={}),
                    api_request("POST", "/api/payments/nepal/esewa/initiate", json={}),
                    api_request("POST", "/api/auth/login", json={}),
                )

        responses = asyncio.run(requests())
        self.assertEqual([response.status_code for response in responses], [503] * 5)
        self.assertTrue(all(response.json().get("maintenance") is True for response in responses))
        self.assertEqual(responses[0].headers["retry-after"], "300")

    def test_admin_status_and_payment_returns_stay_open_during_maintenance(self):
        async def requests():
            with self.on():
                return await asyncio.gather(
                    api_request("GET", "/api/admin/auth/me"),
                    api_request("GET", "/api/admin/maintenance"),
                    api_request("GET", "/api/payments/nepal/esewa/callback"),
                    api_request("GET", "/health/live"),
                )

        admin_me, admin_maintenance, callback, health = asyncio.run(requests())
        self.assertEqual(admin_me.status_code, 401)
        self.assertEqual(admin_maintenance.status_code, 401)
        self.assertEqual(callback.status_code, 400)
        self.assertEqual(health.status_code, 200)

    def test_status_reports_live_when_off(self):
        with patch.object(main, "maintenance_state", AsyncMock(return_value={"enabled": False, "message": "", "until": None, "updatedAt": None})):
            response = asyncio.run(api_request("GET", "/api/site/status"))
        self.assertEqual(response.json(), {"maintenance": False})

    def test_status_decrypts_the_author_contact_details(self):
        content = SimpleNamespace(find_one=AsyncMock(return_value={"value": {"name": main.encrypt_text("Binod Kumar Mahato"), "email": main.encrypt_text("author@example.com")}}))
        settings = SimpleNamespace(find_one=AsyncMock(return_value={}))
        fake_db = {main.CONTENT_COLLECTION: content, main.SETTINGS_COLLECTION: settings}
        with self.on(), patch.object(main, "db", fake_db):
            body = asyncio.run(api_request("GET", "/api/site/status")).json()
        self.assertEqual((body["authorName"], body["contactEmail"]), ("Binod Kumar Mahato", "author@example.com"))

    def test_status_lookup_failures_fail_open(self):
        broken = SimpleNamespace(find_one=AsyncMock(side_effect=RuntimeError("database down")))
        main._maintenance_cache.update(state=None, expires=0.0)
        with patch.object(main, "db", {main.SETTINGS_COLLECTION: broken}):
            state = asyncio.run(main.maintenance_state(force=True))
        self.assertFalse(state["enabled"])
        main._maintenance_cache.update(state=None, expires=0.0)

    def test_maintenance_toggle_requires_an_admin(self):
        response = asyncio.run(api_request("PUT", "/api/admin/maintenance", json={"enabled": True}))
        self.assertEqual(response.status_code, 401)


class StoreUpgradeHelpersTest(unittest.TestCase):
    def test_order_access_tokens_are_bound_to_one_order(self):
        order_id = str(ObjectId())
        token = main.issue_order_access_token(order_id)
        self.assertTrue(main.order_access_token_valid(token, order_id))
        self.assertFalse(main.order_access_token_valid(token, str(ObjectId())))
        self.assertFalse(main.order_access_token_valid("not-a-token", order_id))
        self.assertFalse(main.order_access_token_valid("", order_id))

    def test_session_tokens_are_not_accepted_as_order_access(self):
        order_id = str(ObjectId())
        session_like = main.jwt.encode({"sub": order_id, "jti": "x", "exp": main.now_utc() + timedelta(hours=1)}, main.JWT_SECRET, algorithm="HS256")
        self.assertFalse(main.order_access_token_valid(session_like, order_id))

    def test_csv_cells_neutralize_spreadsheet_formulas(self):
        self.assertEqual(main.csv_cell("=HYPERLINK(\"x\")"), "'=HYPERLINK(\"x\")")
        self.assertEqual(main.csv_cell("+977"), "'+977")
        self.assertEqual(main.csv_cell("Kathmandu"), "Kathmandu")
        self.assertEqual(main.csv_cell(None), "")

    def test_order_transitions_only_move_forward(self):
        self.assertEqual(main.ORDER_TRANSITIONS["pending"], {"cancelled"})
        self.assertNotIn("pending", set().union(*main.ORDER_TRANSITIONS.values()))
        self.assertNotIn("fulfilled", main.ORDER_TRANSITIONS)
        self.assertNotIn("cancelled", main.ORDER_TRANSITIONS)

    def test_category_slugs_are_normalized(self):
        self.assertEqual(main.category_slug("  Short Stories & Essays "), "short-stories-essays")
        self.assertEqual(main.category_slug("!!!"), "")

    def test_stock_adjustments_must_be_nonzero(self):
        with self.assertRaises(ValidationError):
            main.StockAdjustmentInput(delta=0)
        self.assertEqual(main.StockAdjustmentInput(delta=-3).delta, -3)

    def test_public_gallery_route_is_registered(self):
        self.assertIn("/api/gallery", {route.path for route in main.app.routes})


class FakeBackupCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *_args):
        return self

    async def to_list(self, _length=None):
        return [dict(document) for document in self.documents]


class FakeBackupCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    def find(self, *_args):
        return FakeBackupCursor(self.documents)

    async def delete_many(self, query):
        if not query:
            self.documents = []
            return
        clauses = query.get("$or", [query])
        self.documents = [
            document for document in self.documents
            if not any(all(document.get(key) == value for key, value in clause.items()) for clause in clauses)
        ]

    async def insert_many(self, documents, ordered=True):
        self.documents.extend(dict(document) for document in documents)

    async def insert_one(self, document):
        self.documents.append(dict(document))

    async def update_one(self, query, update, upsert=False):
        for document in self.documents:
            if document.get("_id") == query.get("_id"):
                document.update(update.get("$set", {}))
                return
        if upsert:
            self.documents.append({**query, **update.get("$setOnInsert", {}), **update.get("$set", {})})


class FakeBackupDatabase:
    def __init__(self, collections):
        self.collections = {name: FakeBackupCollection(documents) for name, documents in collections.items()}

    async def list_collection_names(self, filter=None):
        return list(self.collections)

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeBackupCollection())

    def __getattr__(self, name):
        return self[name]


def backup_sample_data():
    stamp = main.now_utc().replace(microsecond=0)
    admin_id = ObjectId()
    return {
        "users": [{"_id": admin_id, "email": main.encrypt_text("admin@example.com"), "emailHash": main.email_index("admin@example.com"), "role": "admin", "passwordHash": "hash", "createdAt": stamp}],
        "books": [{"_id": ObjectId(), "title": "The Quiet Between", "priceNpr": 650, "rating": 4.5, "createdAt": stamp}],
        "orders": [{"_id": ObjectId(), "total": 650.0, "customer": {"email": main.encrypt_text("reader@example.com")}, "items": [{"quantity": 1}], "createdAt": stamp}],
        main.SETTINGS_COLLECTION: [{"_id": "store", "storeName": "Author Bookstore"}],
        "auth_sessions": [{"_id": ObjectId(), "tokenHash": "current"}],
    }


def rebuild_backup_zip(data, changes):
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        for info in source.infolist():
            content = changes.get(info.filename, source.read(info))
            if content is not None:
                target.writestr(info.filename, content)
        for name, content in changes.items():
            if name not in source.namelist() and content is not None:
                target.writestr(name, content)
    return buffer.getvalue()


class BackupRestoreTest(unittest.TestCase):
    def build(self, fake_db):
        with patch.object(main, "db", fake_db), patch.object(main, "collect_backup_images", AsyncMock(return_value=({}, {"images": {}, "skipped": []}))):
            return asyncio.run(main.build_backup_archive({"role": "admin"}))

    def test_backup_round_trip_preserves_types_and_skips_sessions(self):
        sample = backup_sample_data()
        data, manifest = self.build(FakeBackupDatabase(sample))
        self.assertIn("database/users.json", zipfile.ZipFile(io.BytesIO(data)).namelist())
        self.assertNotIn("auth_sessions", manifest["collections"])
        _, collections = main.read_backup_archive(data)
        self.assertEqual(collections["books"], sample["books"])
        self.assertEqual(collections["orders"], sample["orders"])
        self.assertEqual(collections["users"][0]["passwordHash"], "hash")
        self.assertIsInstance(collections["users"][0]["_id"], ObjectId)
        self.assertEqual(collections["users"][0]["createdAt"].tzinfo, main.UTC)

    def test_tampered_or_foreign_archives_are_rejected(self):
        data, _ = self.build(FakeBackupDatabase(backup_sample_data()))
        manifest = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
        foreign = json.dumps({**manifest, "keyFingerprint": "0" * 16}).encode()
        cases = {
            "edited data": rebuild_backup_zip(data, {"database/books.json": b"[]"}),
            "edited manifest": rebuild_backup_zip(data, {"manifest.json": json.dumps({**manifest, "createdAt": "x"}).encode()}),
            "other server": rebuild_backup_zip(data, {"manifest.json": foreign}),
            "missing signature": rebuild_backup_zip(data, {"manifest.sig": None}),
            "path traversal": rebuild_backup_zip(data, {"../evil.json": b"[]"}),
            "extra collection": rebuild_backup_zip(data, {"database/extra.json": b"[]"}),
            "not a zip": b"not a zip file",
            "empty": b"",
            "truncated": data[: len(data) // 2],
        }
        for label, archive in cases.items():
            with self.subTest(label), self.assertRaises(main.HTTPException) as raised:
                main.read_backup_archive(archive)
            self.assertEqual(raised.exception.status_code, 400)
            self.assertTrue(raised.exception.detail.startswith("Backup rejected"))

    def test_documents_with_operator_keys_are_rejected(self):
        with self.assertRaises(main.HTTPException):
            main.parse_backup_collection("books", b'[{"_id": 1, "$where": "1"}]', 1)
        with self.assertRaises(main.HTTPException):
            main.parse_backup_collection("users", b'[{"_id": 1, "role": "owner"}]', 1)
        with self.assertRaises(main.HTTPException):
            main.parse_backup_collection("books", b'[{"_id": 1}, {"_id": 1}]', 2)

    def test_restore_replaces_data_and_keeps_the_restoring_admin(self):
        sample = backup_sample_data()
        data, _ = self.build(FakeBackupDatabase(sample))
        current_admin = {"_id": ObjectId(), "email": main.encrypt_text("admin@example.com"), "emailHash": main.email_index("admin@example.com"), "role": "admin", "passwordHash": "new-hash"}
        live = FakeBackupDatabase({
            "users": [current_admin],
            "books": [{"_id": ObjectId(), "title": "Added later"}],
            "newcollection": [{"_id": 1}],
            "auth_sessions": [{"_id": 1, "tokenHash": "current"}, {"_id": 2, "tokenHash": "other"}],
        })

        async def restore():
            _, collections = main.read_backup_archive(data)
            with patch.object(main, "db", live):
                await main.replace_collections({name: collections.get(name, []) for name in set(collections) | set(await main.backup_collection_names())})
                await main.keep_restoring_admin(current_admin)

        asyncio.run(restore())
        self.assertEqual([book["title"] for book in live["books"].documents], ["The Quiet Between"])
        self.assertEqual(live["newcollection"].documents, [])
        self.assertEqual(live["users"].documents, [current_admin])
        self.assertEqual(live["app_metadata"].documents[0]["user"], current_admin["_id"])
        self.assertEqual(len(live["orders"].documents), 1)

    def test_backup_routes_require_an_admin_session(self):
        async def requests():
            return await asyncio.gather(
                api_request("GET", "/api/admin/backup"),
                api_request("POST", "/api/admin/backup/verify", content=b"PK\x03\x04", headers={"Content-Type": "application/zip"}),
                api_request("POST", "/api/admin/backup/restore", content=b"PK\x03\x04", headers={"Content-Type": "application/zip", "X-Confirm-Restore": "RESTORE"}),
            )

        self.assertEqual([response.status_code for response in asyncio.run(requests())], [401, 401, 401])

    def test_only_backup_uploads_accept_large_bodies(self):
        body = b"0" * (2 * 1024 * 1024)

        async def requests():
            return await asyncio.gather(
                api_request("POST", "/api/admin/backup/verify", content=body, headers={"Content-Type": "application/zip"}),
                api_request("POST", "/api/admin/books", content=body, headers={"Content-Type": "application/json"}),
            )

        backup, books = asyncio.run(requests())
        self.assertEqual(backup.status_code, 401)
        self.assertEqual(books.status_code, 413)
        self.assertEqual(main.request_body_limit("/api/admin/backup/restore"), main.BACKUP_MAX_UPLOAD_BYTES)

    def test_backup_permission_is_admin_only(self):
        for role, permissions in main.ROLE_PERMISSIONS.items():
            with self.subTest(role=role):
                self.assertEqual("*" in permissions or "backup:manage" in permissions, role == "admin")

    def test_image_downloads_refuse_private_hosts(self):
        async def check():
            async with httpx.AsyncClient() as client:
                return await asyncio.gather(
                    main.host_is_public("127.0.0.1"),
                    main.host_is_public("10.0.0.5"),
                    main.host_is_public("169.254.169.254"),
                    main.fetch_backup_image(client, "https://127.0.0.1/cover.jpg"),
                    main.fetch_backup_image(client, "http://example.com/cover.jpg"),
                )

        self.assertEqual(asyncio.run(check()), [False, False, False, None, None])

    def test_image_urls_are_collected_from_books_media_and_content(self):
        urls = main.backup_image_urls({
            "books": [{"image": "https://img.example.com/a.jpg"}, {"image": "https://img.example.com/a.jpg"}],
            main.MEDIA_COLLECTION: [{"url": "https://img.example.com/b.jpg"}],
            main.CONTENT_COLLECTION: [{"value": {"portrait": "/local.jpg", "ogImage": "https://img.example.com/c.jpg"}}],
        })
        self.assertEqual(urls, ["https://img.example.com/a.jpg", "https://img.example.com/b.jpg", "https://img.example.com/c.jpg"])

    def test_restored_image_links_are_recognised_and_collected(self):
        name = "0123456789abcdef01234567.jpg"
        self.assertEqual(main.served_image_name(f"https://api.example.com/api/media/files/{name}"), name)
        self.assertEqual(main.served_image_name(f"http://localhost:3000/api/media/files/{name}"), name)
        for url in ("https://x.example.com/api/media/files/../secret.jpg", "https://x.example.com/other/" + name, f"/api/media/files/{name}.exe", None):
            with self.subTest(url=url):
                self.assertIsNone(main.served_image_name(url))
        # Copies served by this site are backed up even on plain-HTTP development origins.
        local = f"http://localhost:3000/api/media/files/{name}"
        self.assertEqual(main.backup_image_urls({"books": [{"image": local}, {"image": "http://insecure.example.com/a.jpg"}]}), [local])

    def test_archive_reader_returns_verified_image_files(self):
        images = {"images/0123456789abcdef01234567.png": b"\x89PNG fake"}
        index = {"images": {"https://img.example.com/a.png": {"file": "images/0123456789abcdef01234567.png", "contentType": "image/png", "bytes": 9}}, "skipped": []}
        with patch.object(main, "db", FakeBackupDatabase(backup_sample_data())), patch.object(main, "collect_backup_images", AsyncMock(return_value=(images, index))):
            data, _ = asyncio.run(main.build_backup_archive({"role": "admin"}))
        _, collections, files = main.read_backup_contents(data)
        self.assertIn("books", collections)
        self.assertEqual(files["images/0123456789abcdef01234567.png"], b"\x89PNG fake")
        self.assertEqual(main.backup_image_index(files), index["images"])

    def test_restored_images_are_served_with_immutable_caching_and_a_sandbox(self):
        name = "0123456789abcdef01234567.svg"
        stored = SimpleNamespace(find_one=AsyncMock(side_effect=lambda query: {"_id": name, "data": b"<svg/>", "contentType": "image/svg+xml"} if query["_id"] == name else None))

        async def requests():
            with patch.object(main, "db", {main.RESTORED_IMAGE_COLLECTION: stored}):
                return await asyncio.gather(
                    api_request("GET", f"/api/media/files/{name}", headers={"Accept-Encoding": "gzip"}),
                    api_request("GET", "/api/media/files/ffffffffffffffffffffffff.svg"),
                    api_request("GET", "/api/media/files/not-a-valid-name.svg"),
                )

        found, missing, invalid = asyncio.run(requests())
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.content, b"<svg/>")
        self.assertEqual(found.headers["cache-control"], "public, max-age=31536000, immutable")
        self.assertIn("sandbox", found.headers["content-security-policy"])
        self.assertNotIn("content-encoding", found.headers)
        self.assertEqual([missing.status_code, invalid.status_code], [404, 404])
        self.assertEqual(missing.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
