from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import smtplib
import socket
import time
import zipfile
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import jwt
from bson import ObjectId, json_util
from bson.errors import InvalidId
from bson.json_util import JSONMode, JSONOptions
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError
from pymongo.errors import DuplicateKeyError
from pymongo import AsyncMongoClient
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

load_dotenv(Path(__file__).with_name(".env"))
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("author_portfolio")

PRODUCTION = (os.getenv("APP_ENV") or os.getenv("NODE_ENV", "")).lower() == "production"
JWT_SECRET = os.getenv("JWT_SECRET", "")
MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "" if PRODUCTION else "mongodb://127.0.0.1:27017/evelyn-hart-portfolio",
)
DB_NAME = os.getenv(
    "MONGODB_DATABASE",
    "" if PRODUCTION else "evelyn-hart-portfolio",
)
FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    os.getenv("CLIENT_ORIGIN", "" if PRODUCTION else "http://localhost:3000"),
).strip().rstrip("/")
WEBSITE_URL = os.getenv("PUBLIC_WEBSITE_URL", FRONTEND_URL).strip().rstrip("/")
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "").strip().rstrip("/")
API_ALLOWED_ORIGINS = os.getenv("API_ALLOWED_ORIGINS", "")
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "strict").lower()
SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").lower()

if PRODUCTION and not MONGODB_URI:
    raise RuntimeError("MONGODB_URI must be configured in production.")


def parse_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"([1-9]\d*)(s|m|h|d)", value.strip().lower())
    if not match:
        raise RuntimeError("JWT_EXPIRES_IN must be a positive duration such as 30m, 8h, or 1d.")
    amount = int(match.group(1))
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    seconds = amount * multiplier
    if seconds > 30 * 24 * 60 * 60:
        raise RuntimeError("JWT_EXPIRES_IN cannot exceed 30 days.")
    return seconds


JWT_EXPIRES_SECONDS = parse_duration_seconds(os.getenv("JWT_EXPIRES_IN", "8h"))
if SESSION_COOKIE_SAMESITE not in {"strict", "lax", "none"}:
    raise RuntimeError("SESSION_COOKIE_SAMESITE must be strict, lax, or none.")
if SESSION_COOKIE_SAMESITE == "none" and not PRODUCTION:
    raise RuntimeError("SESSION_COOKIE_SAMESITE=none requires production HTTPS.")
if SMTP_SECURITY not in {"starttls", "ssl"}:
    raise RuntimeError("SMTP_SECURITY must be starttls or ssl.")
FIELD_KEYS = {"email", "name", "ip", "address", "phone", "notes", "bankAccountNumber", "contactEmail"}
USER_SECRET_KEYS = {"passwordHash", "emailOtpHash", "emailOtpExpiresAt", "loginOtpHash", "loginOtpExpiresAt", "adminLoginOtpHash", "adminLoginOtpExpiresAt", "adminEmailOtpHash", "adminEmailOtpExpiresAt", "adminPasswordResetOtpHash", "adminPasswordResetOtpExpiresAt", "passwordResetOtpHash", "passwordResetOtpExpiresAt", "pendingAdminEmail", "pendingAdminEmailHash", "pendingAdminEmailOtpHash", "pendingAdminEmailOtpExpiresAt", "totpSecret", "totpPendingSecret", "totpRecoveryCodeHashes", "tokenHash", "trackingTokenHash"}
ROLE_PERMISSIONS = {
    "admin": ["*"],
    "manager": ["analytics:read", "books:read", "books:write", "content:read", "content:write", "media:read", "media:write", "users:manage"],
    "editor": ["books:read", "books:write", "content:read", "content:write", "media:read", "media:write"],
    "support": ["content:read", "media:read"],
    "customer": []
}
VALID_ROLES = {"admin", "manager", "editor", "support"}
CONTENT_COLLECTION = "sitecontents"
AUDIT_COLLECTION = "adminaudits"
MEDIA_COLLECTION = "mediaassets"
SETTINGS_COLLECTION = "adminsettings"
NEWSLETTER_COLLECTION = "newslettersubscribers"
CATEGORY_COLLECTION = "storecategories"
NOTIFICATION_COLLECTION = "adminnotifications"
ORDER_TRANSITIONS = {
    "pending": {"cancelled"},
    "paid": {"processing", "cancelled"},
    "processing": {"shipped", "fulfilled", "cancelled"},
    "shipped": {"fulfilled"},
}
ORDER_ACCESS_DAYS = 30
BOOK_FIELDS = {"title", "subtitle", "description", "image", "format", "year", "status", "category", "priceNpr", "stock"}
MEDIA_FIELDS = {"title", "url", "altText", "category", "public", "notes"}
CUSTOMER_FIELDS = {"name", "email", "phone", "address", "notes"}
REVIEW_FIELDS = {"book", "customerName", "rating", "body", "status"}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ENC_PREFIX = "enc:v1:"

if not JWT_SECRET or len(JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET must be set to at least 32 characters.")
encryption_seed = os.getenv("DATA_ENCRYPTION_KEY")
if PRODUCTION and (not encryption_seed or len(encryption_seed) < 32):
    raise RuntimeError("DATA_ENCRYPTION_KEY must be a stable secret of at least 32 characters in production.")
email_index_seed = os.getenv("EMAIL_INDEX_SECRET", "")
if PRODUCTION and len(email_index_seed) < 32:
    raise RuntimeError("EMAIL_INDEX_SECRET must be an independent secret of at least 32 characters in production.")
if PRODUCTION and len({JWT_SECRET, encryption_seed, email_index_seed}) != 3:
    raise RuntimeError("JWT_SECRET, DATA_ENCRYPTION_KEY, and EMAIL_INDEX_SECRET must be different secrets.")
_fernet_key = base64.urlsafe_b64encode(
    hashlib.sha256((encryption_seed or JWT_SECRET).encode("utf-8")).digest()
)
FERNET = Fernet(_fernet_key)
EMAIL_INDEX_SECRET = (email_index_seed or encryption_seed or JWT_SECRET).encode("utf-8")
PASSWORD_HASHER = PasswordHash((Argon2Hasher(), BcryptHasher()))
mongo = AsyncMongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000, tz_aware=True)
db = mongo[DB_NAME]


def validate_https_origin(value: str, label: str) -> str:
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{label} must be a valid HTTPS origin.") from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or "*" in hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    ):
        raise RuntimeError(f"{label} must be a public HTTPS origin without a path.")
    return f"https://{parsed.netloc}".rstrip("/")


def validate_production_config() -> None:
    if not PRODUCTION:
        return
    placeholders = ("replace-with", "change-me", "changeme", "placeholder")
    secrets_to_check = (JWT_SECRET, encryption_seed or "", email_index_seed)
    if any(
        len(secret) < 32 or any(marker in secret.lower() for marker in placeholders)
        for secret in secrets_to_check
    ):
        raise RuntimeError("JWT_SECRET, DATA_ENCRYPTION_KEY, and EMAIL_INDEX_SECRET must be unique random secrets of at least 32 characters.")
    if len({JWT_SECRET, encryption_seed, email_index_seed}) != 3:
        raise RuntimeError("JWT_SECRET, DATA_ENCRYPTION_KEY, and EMAIL_INDEX_SECRET must be different secrets.")
    if not mongo_uri_uses_tls(MONGODB_URI):
        raise RuntimeError("MONGODB_URI must use MongoDB TLS in production.")
    if not DB_NAME.strip():
        raise RuntimeError("MONGODB_DATABASE must be configured in production.")
    admin_email = normalized_email(os.getenv("ADMIN_EMAIL", ""))
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if (
        not EMAIL_PATTERN.fullmatch(admin_email)
        or len(admin_password) < 12
        or not admin_password.strip()
        or any(marker in admin_password.lower() for marker in placeholders)
    ):
        raise RuntimeError("Set a valid ADMIN_EMAIL and an ADMIN_PASSWORD of at least 12 characters.")
    if not API_PUBLIC_URL:
        raise RuntimeError("API_PUBLIC_URL must be configured in production.")
    validate_https_origin(FRONTEND_URL, "FRONTEND_URL")
    validate_https_origin(WEBSITE_URL, "PUBLIC_WEBSITE_URL")
    validate_https_origin(API_PUBLIC_URL, "API_PUBLIC_URL")

    required_mail_settings = ("SMTP_HOST", "SMTP_FROM")
    if any(not os.getenv(name, "").strip() for name in required_mail_settings):
        raise RuntimeError("SMTP_HOST and SMTP_FROM must be configured in production for admin verification and password reset.")
    if any(character.isspace() for character in os.getenv("SMTP_HOST", "")):
        raise RuntimeError("SMTP_HOST must be a hostname without whitespace.")
    _, sender_email = parseaddr(os.getenv("SMTP_FROM", ""))
    if not EMAIL_PATTERN.fullmatch(sender_email):
        raise RuntimeError("SMTP_FROM must contain a valid sender email address.")
    if bool(os.getenv("SMTP_USERNAME")) != bool(os.getenv("SMTP_PASSWORD")):
        raise RuntimeError("SMTP_USERNAME and SMTP_PASSWORD must either both be set or both be empty.")
    if SMTP_SECURITY not in {"starttls", "ssl"}:
        raise RuntimeError("SMTP_SECURITY must be starttls or ssl.")
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT must be a valid TCP port.") from exc
    if not 1 <= smtp_port <= 65535:
        raise RuntimeError("SMTP_PORT must be a valid TCP port.")


def mongo_uri_uses_tls(uri: str) -> bool:
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    scheme = parsed.scheme.lower()
    if scheme not in {"mongodb", "mongodb+srv"} or not parsed.hostname:
        return False
    query = parse_qs(parsed.query)
    if scheme == "mongodb+srv":
        return not any(value.lower() in {"false", "0"} for key in ("tls", "ssl") for value in query.get(key, []))
    return any(value.lower() in {"true", "1"} for key in ("tls", "ssl") for value in query.get(key, []))


def configured_origins() -> set[str]:
    candidates = [FRONTEND_URL]
    if not PRODUCTION:
        candidates.append(os.getenv("CLIENT_ORIGIN", ""))
    candidates.extend(origin.strip() for origin in API_ALLOWED_ORIGINS.split(","))
    if not PRODUCTION:
        candidates.extend(("http://localhost:3000", "http://127.0.0.1:3000"))

    origins: set[str] = set()
    for candidate in candidates:
        value = candidate.strip().rstrip("/")
        if not value:
            continue
        try:
            parsed = urlparse(value)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise RuntimeError("API_ALLOWED_ORIGINS and frontend URL settings must contain valid origins.") from exc
        allowed_development_http = (
            not PRODUCTION
            and parsed.scheme == "http"
            and hostname in {"localhost", "127.0.0.1"}
        )
        if (
            not hostname
            or "*" in hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not allowed_development_http)
        ):
            raise RuntimeError("API_ALLOWED_ORIGINS and frontend URL settings must be HTTPS origins in production.")
        origins.add(f"{parsed.scheme}://{parsed.netloc.lower()}")
    return origins


FRONTEND_ORIGINS = configured_origins()


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=160)


class EmailCodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class NewsletterSubscribeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=320)


class AdminPasswordResetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password must contain a non-whitespace character.")
        return value


class AdminEmailChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AdminPasswordChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    currentPassword: str = Field(min_length=1, max_length=128)
    newPassword: str = Field(min_length=12, max_length=128)

    @field_validator("newPassword")
    @classmethod
    def reject_blank_new_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password must contain a non-whitespace character.")
        return value


class EmailVerificationCodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}$")


class OrderCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    address: str = Field(min_length=5, max_length=500)
    phone: str = Field(default="", max_length=32)


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bookId: str = Field(pattern=r"^[a-fA-F0-9]{24}$")
    quantity: int = Field(ge=1, le=20)


class CheckoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer: OrderCustomer
    items: list[OrderItem] = Field(min_length=1, max_length=20)


class OrderStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=500)
    trackingNumber: str = Field(default="", max_length=120)
    carrier: str = Field(default="", max_length=80)

    @field_validator("note", "trackingNumber", "carrier")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class OrderRefundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(default="", max_length=120)

    @field_validator("reference")
    @classmethod
    def strip_reference(cls, value: str) -> str:
        return value.strip()


class OrderLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orderId: str = Field(pattern=r"^[a-fA-F0-9]{24}$")
    email: EmailStr


class BankReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=3, max_length=120)
    note: str = Field(default="", max_length=300)

    @field_validator("reference", "note")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class CategoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    sortOrder: int | None = Field(default=None, ge=0, le=10000)
    active: bool | None = None

    @field_validator("name", "description")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class StockAdjustmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(default="", max_length=200)

    @field_validator("delta")
    @classmethod
    def reject_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Stock adjustment must not be zero.")
        return value


class AccountStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


class MaintenanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    message: str = Field(default="", max_length=500)
    until: datetime | None = None

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        return value.strip()


class NotificationReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(default_factory=list, max_length=200)


class BankPaymentConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transactionReference: str = Field(default="", max_length=120)

    @field_validator("transactionReference")
    @classmethod
    def normalize_transaction_reference(cls, value: str) -> str:
        return value.strip()


class AdminSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    storeName: str | None = Field(default=None, min_length=1, max_length=120)
    contactEmail: str | None = Field(default=None, max_length=254)
    defaultCurrency: str | None = Field(default=None, pattern=r"^npr$")
    lowStockThreshold: int | None = Field(default=None, ge=0, le=10000)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    bankName: str | None = Field(default=None, max_length=120)
    bankAccountName: str | None = Field(default=None, max_length=160)
    bankAccountNumber: str | None = Field(default=None, max_length=80)
    bankBranch: str | None = Field(default=None, max_length=120)
    bankInstructions: str | None = Field(default=None, max_length=1000)

    @field_validator("bankName", "bankAccountName", "bankAccountNumber", "bankBranch", "bankInstructions")
    @classmethod
    def normalize_bank_details(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class AccountProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


def now_utc() -> datetime:
    return datetime.now(UTC)


def email_index(email: str) -> str:
    normalized = email.strip().lower()
    return hmac.new(EMAIL_INDEX_SECRET, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_text(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    if value.startswith(ENC_PREFIX):
        return value
    token = FERNET.encrypt(value.encode("utf-8")).decode("ascii")
    return f"{ENC_PREFIX}{token}"


def decrypt_text(value: Any) -> Any:
    if not isinstance(value, str) or not value.startswith(ENC_PREFIX):
        return value
    try:
        return FERNET.decrypt(value[len(ENC_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(status_code=500, detail="Stored encrypted data could not be decrypted.") from exc


def encrypt_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [encrypt_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            key: encrypt_text(item) if key in FIELD_KEYS else encrypt_fields(item)
            for key, item in value.items()
        }
    return value


def serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in USER_SECRET_KEYS or key in {"emailHash", "authVersion"}:
                continue
            if key in FIELD_KEYS:
                item = decrypt_text(item)
            result[key] = serialize(item)
        return result
    return value


def require_object_id(raw_id: str, label: str = "record") -> ObjectId:
    if not ObjectId.is_valid(raw_id):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")
    return ObjectId(raw_id)


def normalized_email(raw_email: str) -> str:
    return raw_email.strip().lower()


def is_configured_admin_email(email: str) -> bool:
    configured_email = normalized_email(os.getenv("ADMIN_EMAIL", ""))
    return bool(configured_email) and normalized_email(email) == configured_email


async def find_user_by_email(email: str) -> dict[str, Any] | None:
    address = normalized_email(email)
    return await db.users.find_one({"$or": [{"emailHash": email_index(address)}, {"email": address}]})


def issue_otp(email: str, purpose: str, code: str) -> tuple[str, datetime]:
    digest = hmac.new(
        JWT_SECRET.encode("utf-8"),
        f"{purpose}:{normalized_email(email)}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest, now_utc() + timedelta(minutes=10)


def otp_matches(email: str, purpose: str, code: str, saved_digest: str | None, expires_at: datetime | None) -> bool:
    if not saved_digest or not expires_at or expires_at < now_utc():
        return False
    expected = hmac.new(
        JWT_SECRET.encode("utf-8"),
        f"{purpose}:{normalized_email(email)}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, saved_digest)


async def send_email_code(email: str, code: str, purpose: str) -> None:
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise HTTPException(
            status_code=503,
            detail=(
                "Email delivery is not configured. Set SMTP_HOST and SMTP_FROM "
                "in server/.env, plus SMTP_USERNAME and SMTP_PASSWORD if your mail "
                "relay requires authentication, then restart the API."
            ),
        )
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    if bool(username) != bool(password):
        raise HTTPException(
            status_code=503,
            detail=(
                "SMTP authentication is incomplete. Set both SMTP_USERNAME and "
                "SMTP_PASSWORD in server/.env, then restart the API."
            ),
        )
    subjects = {
        "verify": "Verify your author portfolio account",
        "login": "Your author portfolio sign-in code",
        "admin-verify": "Verify your Admin Panel email",
        "admin-password-reset": "Reset your Admin Panel password",
        "admin-email-change": "Verify your new Admin Panel email",
        "password-reset": "Reset your bookstore account password",
    }
    subject = subjects.get(purpose, "Your author portfolio security code")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = email
    message.set_content(f"Your one-time code is {code}. It expires in 10 minutes. If you did not request it, you can ignore this message.")

    delivery_phase = ["connection"]

    def deliver() -> None:
        port = int(os.getenv("SMTP_PORT", "587"))
        smtp_client = smtplib.SMTP_SSL if SMTP_SECURITY == "ssl" else smtplib.SMTP
        with smtp_client(host, port, timeout=10) as smtp:
            if SMTP_SECURITY == "starttls":
                delivery_phase[0] = "TLS negotiation"
                smtp.starttls()
            if username and password:
                delivery_phase[0] = "authentication"
                smtp.login(username, password)
            delivery_phase[0] = "message submission"
            smtp.send_message(message)

    try:
        await asyncio.to_thread(deliver)
    except smtplib.SMTPAuthenticationError as exc:
        logger.warning("SMTP provider rejected authentication (SMTP %s).", exc.smtp_code)
        raise HTTPException(
            status_code=502,
            detail=(
                "The SMTP provider rejected authentication. Verify SMTP_USERNAME, "
                "SMTP_PASSWORD, and the provider's SMTP authentication policy. For "
                "consumer Gmail, use a Google App Password."
            ),
        ) from exc
    except smtplib.SMTPServerDisconnected as exc:
        logger.warning("SMTP provider disconnected during %s.", delivery_phase[0])
        if delivery_phase[0] == "authentication":
            detail = (
                "The SMTP provider closed the connection during authentication. "
                "Verify the SMTP credentials and provider policy. For consumer "
                "Gmail, use smtp.gmail.com on port 587 with STARTTLS and a Google "
                "App Password. For Workspace relay, confirm the account/sender "
                "policy; if it uses IP allowlisting, clear SMTP_USERNAME and "
                "SMTP_PASSWORD and allowlist this server's public IP."
            )
        else:
            detail = (
                f"The SMTP provider closed the connection during {delivery_phase[0]}. "
                "Check the SMTP host, port, TLS mode, and provider policy."
            )
        raise HTTPException(status_code=502, detail=detail) from exc
    except smtplib.SMTPSenderRefused as exc:
        logger.warning("SMTP relay rejected the configured sender (SMTP %s).", exc.smtp_code)
        raise HTTPException(
            status_code=502,
            detail=(
                "Google Workspace rejected the configured sender. Authorize its "
                "domain and the API server's public IP in the Workspace SMTP relay "
                "policy, or use an authorized Workspace sender address. For a "
                "personal Gmail mailbox, use smtp.gmail.com with a Google App "
                "Password instead of the Workspace relay."
            ),
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        codes = sorted({str(error[0]) for error in exc.recipients.values()})
        logger.warning("SMTP relay rejected recipient(s) (SMTP %s).", ",".join(codes))
        raise HTTPException(
            status_code=502,
            detail=(
                "The SMTP relay rejected the recipient. Verify that the recipient "
                "can receive mail from this relay and that Workspace relay policy "
                "permits delivery."
            ),
        ) from exc
    except smtplib.SMTPDataError as exc:
        logger.warning("SMTP provider rejected message data (SMTP %s).", exc.smtp_code)
        raise HTTPException(
            status_code=502,
            detail=(
                f"The SMTP provider rejected the message after accepting the sender "
                f"and recipient (SMTP {exc.smtp_code}). Check the account's sending "
                "restrictions, daily limits, and provider security alerts."
            ),
        ) from exc
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning(
            "SMTP delivery failed during %s (%s).",
            delivery_phase[0],
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"SMTP delivery failed during {delivery_phase[0]}. Check the "
                "SMTP provider's sending policy and server logs."
            ),
        ) from exc


def cookie_secure(mode: str | None = None) -> bool:
    return PRODUCTION or mode == "live"


def set_session_cookie(response: Response, token: str, *, admin: bool, mode: str | None = None) -> None:
    response.set_cookie(
        "store_admin" if admin else "store_session",
        token,
        httponly=True,
        secure=cookie_secure(mode),
        samesite=SESSION_COOKIE_SAMESITE,
        path="/api/admin" if admin else "/api",
        max_age=JWT_EXPIRES_SECONDS,
    )


def clear_session_cookie(response: Response, *, admin: bool) -> None:
    response.delete_cookie(
        "store_admin" if admin else "store_session",
        httponly=True,
        secure=PRODUCTION,
        samesite=SESSION_COOKIE_SAMESITE,
        path="/api/admin" if admin else "/api",
    )


async def create_session(
    user: dict[str, Any],
    response: Response,
    *,
    admin: bool = False,
) -> dict[str, Any]:
    jti = secrets.token_urlsafe(32)
    expires = now_utc() + timedelta(seconds=JWT_EXPIRES_SECONDS)
    token = jwt.encode(
        {"sub": str(user["_id"]), "role": user.get("role", "customer"), "version": user.get("authVersion", 0), "jti": jti, "exp": expires},
        JWT_SECRET,
        algorithm="HS256",
    )
    await db.auth_sessions.insert_one({
        "tokenHash": hashlib.sha256(jti.encode("utf-8")).hexdigest(),
        "user": user["_id"],
        "kind": "admin" if admin else "user",
        "expiresAt": expires,
        "createdAt": now_utc(),
    })
    set_session_cookie(response, token, admin=admin)
    return {
        "id": str(user["_id"]),
        "email": decrypt_text(user.get("email", "")),
        "role": user.get("role", "customer"),
        "permissions": ROLE_PERMISSIONS.get(user.get("role", "customer"), []),
    }


async def authenticated_user(
    request: Request,
    admin_only: bool = False,
) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    token = ""
    admin_cookie = request.cookies.get("store_admin", "")
    if admin_cookie:
        token = admin_cookie
    elif authorization.startswith("Bearer "):
        token = authorization[7:]
    elif not admin_only:
        token = request.cookies.get("store_session", "")
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in.")
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"require": ["sub", "exp", "jti"]})
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.") from exc
    session_hash = hashlib.sha256(claims["jti"].encode("utf-8")).hexdigest()
    session = await db.auth_sessions.find_one({"tokenHash": session_hash, "user": ObjectId(claims["sub"]), "expiresAt": {"$gt": now_utc()}})
    user = await db.users.find_one({"_id": ObjectId(claims["sub"])})
    if not session or not user or not user.get("active", True) or claims.get("version", 0) != user.get("authVersion", 0):
        raise HTTPException(status_code=401, detail="This account is inactive or its session has been revoked.")
    if claims.get("role") != user.get("role"):
        raise HTTPException(status_code=401, detail="This account's access has changed.")
    if admin_only and not is_configured_admin_email(decrypt_text(user.get("email", ""))):
        raise HTTPException(status_code=403, detail="This account is not authorized for the Admin Panel.")
    if admin_only and user.get("role") not in VALID_ROLES:
        raise HTTPException(status_code=403, detail="Administrator access required.")
    if admin_only and session.get("kind") != "admin":
        raise HTTPException(status_code=403, detail="Sign in through the Admin Panel to access this resource.")
    if admin_only and not user.get("emailVerified"):
        raise HTTPException(status_code=403, detail="Verify your admin email address before accessing this resource.")
    request.state.session_hash = session_hash
    request.state.admin_session = session.get("kind") == "admin"
    return user


async def require_admin(request: Request) -> dict[str, Any]:
    user = await authenticated_user(request, admin_only=True)
    return user


def frontend_origins() -> set[str]:
    return FRONTEND_ORIGINS


def require_frontend_origin(request: Request) -> None:
    if request.headers.get("origin", "").rstrip("/") not in frontend_origins():
        raise HTTPException(status_code=403, detail="Request origin was rejected.")


async def require_admin_mutation(request: Request, user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    require_frontend_origin(request)
    return user


def require_permission(permission: str):
    async def dependency(request: Request, user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        granted = ROLE_PERMISSIONS.get(user.get("role", ""), [])
        if "*" not in granted and permission not in granted:
            raise HTTPException(status_code=403, detail="Your role does not allow this action.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_frontend_origin(request)
        return user
    return dependency


async def audit(user: dict[str, Any], action: str, resource: str, resource_id: str = "", details: dict[str, Any] | None = None, ip: str = "") -> None:
    await db[AUDIT_COLLECTION].insert_one({
        "user": user["_id"],
        "action": action,
        "resource": resource,
        "resourceId": str(resource_id),
        "details": details or {},
        "ip": encrypt_text(ip[:64]),
        "createdAt": now_utc(),
    })


def request_ip(request: Request) -> str:
    return request.client.host if request.client else ""


class RequestBodyTooLarge(Exception):
    pass


DEFAULT_MAX_BODY_BYTES = 1_048_576
BACKUP_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
# Only the backup upload routes accept large bodies; every other route keeps the 1 MB limit.
BACKUP_UPLOAD_PATHS = {"/api/admin/backup/verify", "/api/admin/backup/restore"}


def request_body_limit(path: str, default: int = DEFAULT_MAX_BODY_BYTES) -> int:
    return BACKUP_MAX_UPLOAD_BYTES if path in BACKUP_UPLOAD_PATHS else default


class RequestSizeLimitMiddleware:
    def __init__(self, app, maximum_bytes: int = DEFAULT_MAX_BODY_BYTES):
        self.app = app
        self.maximum_bytes = maximum_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        maximum_bytes = request_body_limit(scope.get("path", ""), self.maximum_bytes)
        content_length = next(
            (value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == b"content-length"),
            "",
        )
        if content_length.isdigit() and int(content_length) > maximum_bytes:
            response = JSONResponse({"error": "Request body is too large."}, status_code=413)
            await response(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > maximum_bytes:
                    raise RequestBodyTooLarge()
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            response = JSONResponse({"error": "Request body is too large."}, status_code=413)
            await response(scope, receive, send)


RATE_LIMIT_ROUTES = {
    "/health/live",
    "/health/ready",
    "/api/books",
    "/api/store/books",
    "/api/store/settings",
    "/api/gallery",
    "/api/content",
    "/api/newsletter/subscribe",
    "/api/admin/auth/login",
    "/api/admin/auth/email/request",
    "/api/admin/auth/email/verify",
    "/api/admin/auth/password/request",
    "/api/admin/auth/password/reset",
    "/api/admin/auth/logout",
    "/api/admin/auth/me",
    "/api/admin/analytics",
    "/api/admin/store/analytics",
    "/api/admin/settings",
    "/api/admin/orders",
    "/api/admin/payments",
    "/api/admin/customers",
    "/api/admin/users",
    "/api/admin/books",
    "/api/admin/media",
    "/api/admin/content",
    "/api/admin/audit",
    "/api/admin/categories",
    "/api/admin/notifications",
    "/api/admin/notifications/read",
    "/api/orders/lookup",
    "/api/auth/register",
    "/api/auth/verify-email",
    "/api/auth/resend-verification",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/password/request",
    "/api/auth/password/reset",
    "/api/account/orders",
    "/api/account/profile",
    "/api/account/password",
    "/api/admin/accounts",
    "/api/admin/maintenance",
    "/api/admin/backup",
    "/api/admin/backup/verify",
    "/api/admin/backup/restore",
    "/api/site/status",
}


MAINTENANCE_CACHE_SECONDS = 5
_maintenance_cache: dict[str, Any] = {"state": None, "expires": 0.0}
# Public API areas closed while maintenance is on. The Admin Panel, health checks, the status
# endpoint, and payment-provider callbacks/tracking stay open so in-flight payments still settle.
MAINTENANCE_BLOCKED_PREFIXES = (
    "/api/store", "/api/books", "/api/content", "/api/gallery", "/api/orders",
    "/api/auth", "/api/account", "/api/newsletter",
    "/api/payments/nepal/esewa/initiate", "/api/payments/nepal/khalti/initiate",
)


async def maintenance_state(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    cached = _maintenance_cache["state"]
    if cached is not None and not force and now < _maintenance_cache["expires"]:
        return cached
    try:
        record = await db[SETTINGS_COLLECTION].find_one({"_id": "maintenance"}) or {}
        if not isinstance(record, dict):
            raise TypeError("maintenance record is not a document")
    except Exception:  # noqa: BLE001 - any failure here must fail open, never take the site down
        # Keep the last known state (or "live") and back off before asking the database again.
        logger.warning("Maintenance status could not be read; serving the site normally.")
        fallback = cached or {"enabled": False, "message": "", "until": None, "updatedAt": None}
        _maintenance_cache.update(state=fallback, expires=now + MAINTENANCE_CACHE_SECONDS)
        return fallback
    until = record.get("until")
    state = {
        "enabled": bool(record.get("enabled")),
        "message": record.get("message", ""),
        "until": until if isinstance(until, datetime) else None,
        "updatedAt": record.get("updatedAt"),
    }
    _maintenance_cache.update(state=state, expires=now + MAINTENANCE_CACHE_SECONDS)
    return state


class MaintenanceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith(MAINTENANCE_BLOCKED_PREFIXES) or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        state = await maintenance_state()
        if not state["enabled"]:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"error": "The website is temporarily down for maintenance. Please check back soon.", "maintenance": True},
            status_code=503,
            headers={"Retry-After": "300", "Cache-Control": "no-store"},
        )
        await response(scope, receive, send)


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()
        self.last_cleanup = time.monotonic()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        path = request.url.path
        if path in {"/health/live", "/health/ready", "/api/site/status"}:
            await self.app(scope, receive, send)
            return
        ip = request.client.host if request.client else "unknown"
        # Tracking requires a random cookie token, so status polling gets its own, larger bucket.
        tracking = path.startswith("/api/payments/nepal/track/")
        sensitive = not tracking and any(part in path for part in ("/auth/login", "/auth/otp", "/auth/email", "/auth/password", "/auth/code", "/auth/register", "/auth/verify-email", "/auth/resend-verification", "/newsletter/subscribe", "/payments/nepal/", "/orders/bank-transfer", "/orders/lookup", "/admin/backup/verify", "/admin/backup/restore"))
        restored_image = path.startswith(SERVED_IMAGE_PREFIX)
        limit = 8 if "/auth/login" in path else 12 if sensitive else 60 if tracking else 600 if restored_image else 150
        window = 15 * 60
        path_parts = path.strip("/").split("/")
        if (
            len(path_parts) == 4
            and path_parts[:2] == ["api", "admin"]
            and path_parts[2] in {"users", "books", "media", "content", "customers", "orders", "payments", "categories", "accounts"}
        ):
            rate_limit_path = f"/api/admin/{path_parts[2]}/:id"
        elif len(path_parts) == 5 and path_parts[:2] == ["api", "admin"]:
            rate_limit_path = f"/api/admin/{path_parts[2]}/:id/action"
        elif tracking:
            rate_limit_path = "/api/payments/nepal/track/:id"
        elif restored_image:
            rate_limit_path = SERVED_IMAGE_PREFIX + ":name"
        elif len(path_parts) == 4 and path_parts[:3] == ["api", "store", "books"]:
            rate_limit_path = "/api/store/books/:id"
        elif path in RATE_LIMIT_ROUTES:
            rate_limit_path = path
        else:
            rate_limit_path = "/api/other" if path.startswith("/api/") else "/other"
        key = f"{ip}:{rate_limit_path}"
        current = time.monotonic()
        async with self.lock:
            bucket = self.events[key]
            while bucket and current - bucket[0] > window:
                bucket.popleft()
            if current - self.last_cleanup > 600:
                for stale_key in [k for k, values in self.events.items() if not values or current - values[-1] > window]:
                    self.events.pop(stale_key, None)
                self.last_cleanup = current
            if len(bucket) >= limit:
                response = JSONResponse({"error": "Too many requests. Please try again later."}, status_code=429, headers={"Retry-After": str(max(1, int(window - (current - bucket[0]))))})
                await response(scope, receive, send)
                return
            bucket.append(current)
        await self.app(scope, receive, send)


async def connect_db() -> None:
    if PRODUCTION and not mongo_uri_uses_tls(MONGODB_URI):
        raise RuntimeError("MongoDB TLS must be enabled in production.")
    await mongo.admin.command("ping")
    await encrypt_legacy_records()
    await db.auth_sessions.create_index("tokenHash", unique=True)
    await db.auth_sessions.create_index("expiresAt", expireAfterSeconds=0)
    await db.users.create_index("emailHash", unique=True, sparse=True)
    await db.customers.create_index("emailHash", unique=True, sparse=True)
    await db[NEWSLETTER_COLLECTION].create_index("emailHash", unique=True)
    await db.payments.create_index([("order", 1), ("provider", 1)])
    await db.orders.create_index([("createdAt", -1)])
    await db.orders.create_index([("customerRecord", 1), ("createdAt", -1)])
    await db[AUDIT_COLLECTION].create_index([("createdAt", -1)])
    await db[CATEGORY_COLLECTION].create_index("slug", unique=True)
    await db[NOTIFICATION_COLLECTION].create_index("createdAt", expireAfterSeconds=180 * 24 * 60 * 60, name="notification_ttl")
    # Read-path indexes for the catalogue, account history, and admin lists (all sorted newest first).
    await db.books.create_index([("createdAt", -1)])
    await db.orders.create_index([("user", 1), ("createdAt", -1)])
    await db.payments.create_index([("createdAt", -1)])
    await db.payments.create_index([("provider", 1), ("status", 1)])
    await db.customers.create_index([("createdAt", -1)])
    await db.users.create_index([("role", 1), ("createdAt", -1)])
    await db[MEDIA_COLLECTION].create_index([("category", 1), ("public", 1), ("createdAt", -1)])
    await db[CONTENT_COLLECTION].create_index("key")
    await db[NOTIFICATION_COLLECTION].create_index([("read", 1)])
    await bootstrap_admin()
    await seed_books()
    await stock_sample_books()


async def encrypt_legacy_records() -> None:
    if await db.app_metadata.find_one({"_id": "field-encryption-v3"}):
        return
    for collection_name in ("users", "customers"):
        async for record in db[collection_name].find({"email": {"$type": "string"}}):
            email = normalized_email(str(decrypt_text(record.get("email", ""))))
            updates = {"email": encrypt_text(email), "emailHash": email_index(email), "updatedAt": record.get("updatedAt", now_utc())}
            for key in ("name", "address", "phone", "notes"):
                if key in record:
                    updates[key] = encrypt_text(record[key])
            if collection_name == "users":
                updates["emailVerified"] = record.get("emailVerified", True)
            await db[collection_name].update_one({"_id": record["_id"]}, {"$set": updates})
    async for review in db.reviews.find({"$or": [{"email": {"$type": "string"}}, {"customerName": {"$type": "string"}}]}):
        updates = {
            key: encrypt_text(review[key])
            for key in ("email", "customerName")
            if key in review
        }
        await db.reviews.update_one({"_id": review["_id"]}, {"$set": updates})
    for collection_name in ("orders", "payments", AUDIT_COLLECTION, CONTENT_COLLECTION, SETTINGS_COLLECTION):
        async for record in db[collection_name].find():
            updates: dict[str, Any] = {}
            for key in ("customer", "paymentReference", "providerReference", "providerTransactionId", "ip", "value"):
                if key in record:
                    updates[key] = encrypt_fields(record[key]) if key in {"customer", "value"} else encrypt_text(record[key])
            if collection_name == SETTINGS_COLLECTION:
                for key in ("bankAccountNumber", "contactEmail"):
                    if key in record:
                        updates[key] = encrypt_text(str(record[key]))
            if updates:
                await db[collection_name].update_one({"_id": record["_id"]}, {"$set": updates})
    await db.app_metadata.insert_one({"_id": "field-encryption-v3", "completedAt": now_utc()})


async def bootstrap_admin() -> None:
    email = normalized_email(os.getenv("ADMIN_EMAIL", ""))
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not EMAIL_PATTERN.fullmatch(email) or len(password) < 12 or not password.strip():
        raise RuntimeError("Set ADMIN_EMAIL and an ADMIN_PASSWORD of at least 12 characters.")
    bootstrap = await db.app_metadata.find_one({"_id": "bootstrap-admin"})
    if bootstrap:
        user = await db.users.find_one({"_id": bootstrap["user"]})
        if not user:
            raise RuntimeError("The configured bootstrap administrator no longer exists.")
        email_changed = decrypt_text(user.get("email", "")) != email
        verification_migration = not bootstrap.get("emailVerificationEnforced")
        if email_changed:
            collision = await find_user_by_email(email)
            if collision and collision["_id"] != user["_id"]:
                raise RuntimeError("ADMIN_EMAIL is already assigned to another account.")
        if email_changed or verification_migration:
            await db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "email": encrypt_text(email),
                        "emailHash": email_index(email),
                        "emailVerified": False,
                        "authVersion": user.get("authVersion", 0) + 1,
                        "updatedAt": now_utc(),
                    },
                    "$unset": {
                        "adminEmailOtpHash": "",
                        "adminEmailOtpExpiresAt": "",
                        "adminPasswordResetOtpHash": "",
                        "adminPasswordResetOtpExpiresAt": "",
                    },
                },
            )
            await db.auth_sessions.delete_many({"user": user["_id"]})
        if verification_migration:
            await db.app_metadata.update_one(
                {"_id": "bootstrap-admin"},
                {"$set": {"emailVerificationEnforced": True}},
            )
        return

    existing = await find_user_by_email(email)
    if existing:
        if existing.get("role") not in VALID_ROLES:
            raise RuntimeError("ADMIN_EMAIL is already assigned to a non-admin account.")
        user_id = existing["_id"]
        await db.users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "emailVerified": False,
                    "authVersion": existing.get("authVersion", 0) + 1,
                    "updatedAt": now_utc(),
                },
                "$unset": {
                    "adminEmailOtpHash": "",
                    "adminEmailOtpExpiresAt": "",
                    "adminPasswordResetOtpHash": "",
                    "adminPasswordResetOtpExpiresAt": "",
                },
            },
        )
        await db.auth_sessions.delete_many({"user": user_id})
    else:
        result = await db.users.insert_one({
            "email": encrypt_text(email),
            "emailHash": email_index(email),
            "passwordHash": PASSWORD_HASHER.hash(password),
            "authVersion": 0,
            "role": "admin",
            "active": True,
            "emailVerified": False,
            "createdAt": now_utc(),
            "updatedAt": now_utc(),
        })
        user_id = result.inserted_id
    await db.app_metadata.insert_one({
        "_id": "bootstrap-admin",
        "user": user_id,
        "emailVerificationEnforced": True,
        "createdAt": now_utc(),
    })


async def seed_books() -> None:
    if await db.books.count_documents({}) > 0:
        return
    books = [
        {"title": "The Quiet Between", "subtitle": "A novel of homecoming", "description": "A story of homecoming, family and the courage to begin again.", "image": "https://images.unsplash.com/photo-1544947950-fa07a98d237f?auto=format&fit=crop&w=800&q=85", "format": "Novel", "year": 2025, "status": "published"},
        {"title": "A Map of Small Things", "subtitle": "Finding wonder, one day at a time", "description": "A tender collection of essays about noticing the life already unfolding around us.", "image": "https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=800&q=85", "format": "Essays", "year": 2024, "status": "published"},
        {"title": "The Wildflower Season", "subtitle": "A story of courage & becoming", "description": "A luminous story about the families we inherit, the ones we choose, and the courage to grow toward the light.", "image": "https://images.unsplash.com/photo-1519682337058-a94d519337bc?auto=format&fit=crop&w=800&q=85", "format": "Novel", "year": 2023, "status": "published"},
        {"title": "Letters to the Sea", "subtitle": "A coastal story of second chances", "description": "A box of unsent letters washes ashore, connecting three generations of women on the Oregon coast.", "image": "https://images.unsplash.com/photo-1513001900722-370f803f498d?auto=format&fit=crop&w=800&q=85", "format": "Novel", "year": 2022, "status": "published"},
    ]
    stamp = now_utc()
    await db.books.insert_many([{**book, "createdAt": stamp, "updatedAt": stamp} for book in books])


SAMPLE_STORE_DETAILS = {
    "The Quiet Between": {"priceNpr": 650, "stock": 25, "category": "Novel"},
    "A Map of Small Things": {"priceNpr": 480, "stock": 25, "category": "Essays"},
    "The Wildflower Season": {"priceNpr": 720, "stock": 25, "category": "Novel"},
    "Letters to the Sea": {"priceNpr": 550, "stock": 25, "category": "Novel"},
}


async def stock_sample_books() -> None:
    # One-time: make the bundled sample books purchasable. Only fields an admin has never set are
    # filled, and the marker stops this from re-adding stock after the admin changes it.
    if await db.app_metadata.find_one({"_id": "sample-store-v1"}):
        return
    for title, details in SAMPLE_STORE_DETAILS.items():
        book = await db.books.find_one({"title": title}, {"priceNpr": 1, "stock": 1, "category": 1})
        if not book:
            continue
        missing = {key: value for key, value in details.items() if not book.get(key)}
        if missing:
            await db.books.update_one({"_id": book["_id"]}, {"$set": {**missing, "updatedAt": now_utc()}})
    for order, name in enumerate(("Novel", "Essays"), start=1):
        await db[CATEGORY_COLLECTION].update_one(
            {"slug": category_slug(name)},
            {"$setOnInsert": {"name": name, "slug": category_slug(name), "description": "", "sortOrder": order, "active": True, "createdAt": now_utc(), "updatedAt": now_utc()}},
            upsert=True,
        )
    await db.app_metadata.insert_one({"_id": "sample-store-v1", "createdAt": now_utc()})


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_production_config()
    await connect_db()
    yield
    await mongo.close()


app = FastAPI(
    title="Author Portfolio API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if not PRODUCTION else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if not PRODUCTION else None,
)
origins = FRONTEND_ORIGINS
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(MaintenanceMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Confirm-Restore"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > request_body_limit(request.url.path):
        return JSONResponse({"error": "Request body is too large."}, status_code=413)
    response = await call_next(request)
    cacheable = request.method == "GET" and response.status_code == 200 and public_cacheable_path(request.url.path)
    if cacheable:
        response = await with_etag(request, response)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Public catalogue reads may be stored but must be revalidated, so polling clients get a
    # tiny 304 when nothing changed. Everything else (sessions, admin, orders) is never stored.
    restored_image_file = response.status_code == 200 and request.url.path.startswith(SERVED_IMAGE_PREFIX)
    if not restored_image_file:
        response.headers["Cache-Control"] = "no-cache" if cacheable else "no-store"
    if PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


PUBLIC_CACHEABLE_PATHS = {"/api/books", "/api/store/books", "/api/store/settings", "/api/content", "/api/gallery"}


def public_cacheable_path(path: str) -> bool:
    if path in PUBLIC_CACHEABLE_PATHS:
        return True
    parts = path.strip("/").split("/")
    return len(parts) == 4 and parts[:3] == ["api", "store", "books"]


async def with_etag(request: Request, response: Response) -> Response:
    body = b"".join([chunk async for chunk in response.body_iterator])
    etag = f'W/"{hashlib.sha256(body).hexdigest()[:32]}"'
    headers = {key: value for key, value in response.headers.items() if key.lower() not in {"content-length", "etag"}}
    headers["ETag"] = etag
    if etag in {tag.strip() for tag in request.headers.get("if-none-match", "").split(",")}:
        headers.pop("content-type", None)
        return Response(status_code=304, headers=headers)
    return Response(content=body, status_code=response.status_code, headers=headers)


class CompressionMiddleware:
    """Gzips JSON and CSV responses; backup ZIP archives are already compressed and stream as-is."""

    def __init__(self, app):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024, compresslevel=6)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope.get("path", "").startswith(("/api/admin/backup", SERVED_IMAGE_PREFIX)):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)


# Registered after security_headers so it is the outermost layer and ETags hash the plain body.
app.add_middleware(CompressionMiddleware)


@app.get("/health/live", include_in_schema=False)
async def health_liveness():
    return {"status": "ok"}


async def check_database_connection() -> None:
    await mongo.admin.command("ping")


@app.get("/health/ready", include_in_schema=False)
async def health_readiness():
    try:
        await check_database_connection()
    except PyMongoError as exc:
        logger.warning("Readiness check failed because MongoDB is unavailable.")
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    return {"status": "ready"}


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "Request validation failed."
    return JSONResponse({"error": message}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(DuplicateKeyError)
async def duplicate_key_handler(_: Request, exc: DuplicateKeyError):
    logger.info("A unique MongoDB constraint rejected an API write (error %s).", exc.code)
    return JSONResponse({"error": "A record with that email, slug, or key already exists."}, status_code=409)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc):
    details = getattr(exc, "errors", lambda: [])()
    message = "; ".join(".".join(str(part) for part in item["loc"][1:]) + ": " + item["msg"] for item in details)
    return JSONResponse({"error": message or "Request validation failed."}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):
    logger.exception("Unhandled API error.", exc_info=exc)
    return JSONResponse({"error": "An unexpected server error occurred."}, status_code=500)


async def create_user_login(response: Response, *, email: str, password: str, admin: bool = False, request: Request | None = None) -> dict[str, Any]:
    address = normalized_email(email)
    if admin and not is_configured_admin_email(address):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    user = await find_user_by_email(address)
    if not user or not user.get("active", True):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    try:
        verified, upgraded_hash = PASSWORD_HASHER.verify_and_update(password, user.get("passwordHash", ""))
    except (UnknownHashError, ValueError, TypeError):
        verified, upgraded_hash = False, None
    if not verified or (admin and user.get("role") not in VALID_ROLES):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if upgraded_hash:
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"passwordHash": upgraded_hash, "emailHash": email_index(address), "email": encrypt_text(address), "updatedAt": now_utc()}})
        user["passwordHash"] = upgraded_hash
        user["email"] = encrypt_text(address)
        user["emailHash"] = email_index(address)
    elif not user.get("emailHash"):
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"emailHash": email_index(address), "email": encrypt_text(address), "updatedAt": now_utc()}})
        user["email"] = encrypt_text(address)
        user["emailHash"] = email_index(address)
    if not user.get("emailVerified", False):
        raise HTTPException(status_code=403, detail="Verify your email address before signing in.")
    public_user = await create_session(user, response, admin=admin)
    if admin:
        await audit(user, "login", "session", str(user["_id"]), ip=request_ip(request) if request else "")
    return {"user": public_user}


def customer_view(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(user["_id"]),
        "email": decrypt_text(user.get("email", "")),
        "name": decrypt_text(user.get("name", "")),
        "phone": decrypt_text(user.get("phone", "")),
        "address": decrypt_text(user.get("address", "")),
        "emailVerified": bool(user.get("emailVerified")),
        "createdAt": serialize(user.get("createdAt")),
    }


async def customer_session(request: Request) -> dict[str, Any] | None:
    # Customers authenticate only with the store_session cookie; admin cookies and bearer tokens are ignored here.
    token = request.cookies.get("store_session", "")
    if not token or len(token) > 2000:
        return None
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"require": ["sub", "exp", "jti"]})
        user_id = ObjectId(claims["sub"])
    except (jwt.InvalidTokenError, InvalidId, TypeError):
        return None
    session = await db.auth_sessions.find_one({
        "tokenHash": hashlib.sha256(claims["jti"].encode("utf-8")).hexdigest(),
        "user": user_id,
        "kind": "user",
        "expiresAt": {"$gt": now_utc()},
    })
    user = await db.users.find_one({"_id": user_id}) if session else None
    if (
        not user
        or user.get("role") != "customer"
        or claims.get("role") != "customer"
        or not user.get("active", True)
        or not user.get("emailVerified")
        or claims.get("version", 0) != user.get("authVersion", 0)
    ):
        return None
    return user


async def require_customer(request: Request) -> dict[str, Any]:
    user = await customer_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in to your account.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_frontend_origin(request)
    return user


async def link_customer_orders(user: dict[str, Any]) -> None:
    # Guest orders placed with this verified email address join the account.
    customer = await db.customers.find_one({"emailHash": user.get("emailHash")}, {"_id": 1})
    if customer:
        await db.orders.update_many({"customerRecord": customer["_id"], "user": {"$exists": False}}, {"$set": {"user": user["_id"]}})


@app.post("/api/auth/register", status_code=201)
async def register(payload: RegisterInput, request: Request):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    if not payload.password.strip() or not payload.name.strip():
        raise HTTPException(status_code=422, detail="Enter your name and a password of at least 12 characters.")
    existing = await find_user_by_email(email)
    if existing and (existing.get("role") != "customer" or existing.get("emailVerified")):
        raise HTTPException(status_code=409, detail="An account with this email already exists. Sign in or reset your password.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest, expires = issue_otp(email, "verify", code)
    fields = {
        "email": encrypt_text(email),
        "emailHash": email_index(email),
        "name": encrypt_text(payload.name.strip()),
        "passwordHash": PASSWORD_HASHER.hash(payload.password),
        "role": "customer",
        "active": True,
        "emailVerified": False,
        "emailOtpHash": digest,
        "emailOtpExpiresAt": expires,
        "updatedAt": now_utc(),
    }
    if existing:
        # An unverified registration can be restarted, e.g. after a lost code.
        await db.users.update_one({"_id": existing["_id"]}, {"$set": fields})
    else:
        await db.users.insert_one({**fields, "authVersion": 0, "createdAt": now_utc()})
    await send_email_code(email, code, "verify")
    return {"message": "We sent a 6-digit verification code to your email address."}


@app.post("/api/auth/verify-email")
async def verify_email(payload: EmailCodeInput, request: Request, response: Response):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    user = await find_user_by_email(email)
    if not user or user.get("role") != "customer" or not otp_matches(email, "verify", payload.code, user.get("emailOtpHash"), user.get("emailOtpExpiresAt")):
        raise HTTPException(status_code=400, detail="The verification code is invalid or expired.")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"emailVerified": True, "updatedAt": now_utc()}, "$unset": {"emailOtpHash": "", "emailOtpExpiresAt": ""}})
    user["emailVerified"] = True
    await link_customer_orders(user)
    await create_session(user, response)
    return {"user": customer_view(user)}


@app.post("/api/auth/resend-verification")
async def resend_verification(payload: EmailInput, request: Request):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    user = await find_user_by_email(email)
    if user and user.get("role") == "customer" and not user.get("emailVerified"):
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest, expires = issue_otp(email, "verify", code)
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"emailOtpHash": digest, "emailOtpExpiresAt": expires, "updatedAt": now_utc()}})
        await send_email_code(email, code, "verify")
    return {"message": "If this email needs verification, a new code is on its way."}


@app.post("/api/auth/login")
async def user_login(payload: LoginInput, request: Request, response: Response):
    require_frontend_origin(request)
    user = await find_user_by_email(str(payload.email))
    if not user or user.get("role") != "customer":
        # Staff sign in through the Admin Panel, never the storefront.
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    await create_user_login(response, email=str(payload.email), password=payload.password)
    user = await find_user_by_email(str(payload.email))
    await link_customer_orders(user)
    return {"user": customer_view(user)}


@app.post("/api/auth/logout", status_code=204)
async def user_logout(request: Request, response: Response):
    require_frontend_origin(request)
    token = request.cookies.get("store_session", "")
    if token:
        try:
            claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"require": ["jti"]})
            await db.auth_sessions.delete_one({"tokenHash": hashlib.sha256(claims["jti"].encode("utf-8")).hexdigest()})
        except jwt.InvalidTokenError:
            pass
    clear_session_cookie(response, admin=False)
    response.status_code = 204
    return response


@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = await customer_session(request)
    return {"user": customer_view(user) if user else None}


@app.post("/api/auth/password/request")
async def request_password_reset(payload: EmailInput, request: Request):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    user = await find_user_by_email(email)
    if user and user.get("role") == "customer" and user.get("active", True):
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest, expires = issue_otp(email, "password-reset", code)
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"passwordResetOtpHash": digest, "passwordResetOtpExpiresAt": expires, "updatedAt": now_utc()}})
        await send_email_code(email, code, "password-reset")
    return {"message": "If an account uses this email, a reset code is on its way."}


@app.post("/api/auth/password/reset")
async def reset_password(payload: AdminPasswordResetInput, request: Request):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    user = await find_user_by_email(email)
    if not user or user.get("role") != "customer" or not otp_matches(email, "password-reset", payload.code, user.get("passwordResetOtpHash"), user.get("passwordResetOtpExpiresAt")):
        raise HTTPException(status_code=400, detail="The reset code is invalid or expired.")
    await db.users.update_one({"_id": user["_id"]}, {
        "$set": {"passwordHash": PASSWORD_HASHER.hash(payload.password), "emailVerified": True, "authVersion": user.get("authVersion", 0) + 1, "updatedAt": now_utc()},
        "$unset": {"passwordResetOtpHash": "", "passwordResetOtpExpiresAt": ""},
    })
    await db.auth_sessions.delete_many({"user": user["_id"]})
    return {"message": "Your password was reset. You can now sign in."}


@app.get("/api/account/orders")
async def account_orders(user: dict[str, Any] = Depends(require_customer)):
    orders = await db.orders.find({"user": user["_id"]}).sort("createdAt", -1).limit(100).to_list(100)
    return {"orders": [(await order_tracking_view(order))["order"] for order in orders]}


@app.patch("/api/account/profile")
async def update_profile(payload: AccountProfileInput, user: dict[str, Any] = Depends(require_customer)):
    updates = {key: value.strip() for key, value in payload.model_dump(exclude_unset=True).items() if value is not None}
    if "name" in updates and not updates["name"]:
        raise HTTPException(status_code=422, detail="Your name cannot be empty.")
    if updates:
        await db.users.update_one({"_id": user["_id"]}, {"$set": {**encrypt_fields(updates), "updatedAt": now_utc()}})
    return {"user": customer_view(await db.users.find_one({"_id": user["_id"]}))}


@app.post("/api/account/password")
async def change_customer_password(payload: AdminPasswordChangeInput, response: Response, user: dict[str, Any] = Depends(require_customer)):
    try:
        verified, _ = PASSWORD_HASHER.verify_and_update(payload.currentPassword, user.get("passwordHash", ""))
    except (UnknownHashError, ValueError, TypeError):
        verified = False
    if not verified:
        raise HTTPException(status_code=400, detail="Your current password is incorrect.")
    version = user.get("authVersion", 0) + 1
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"passwordHash": PASSWORD_HASHER.hash(payload.newPassword), "authVersion": version, "updatedAt": now_utc()}})
    await db.auth_sessions.delete_many({"user": user["_id"]})
    await create_session({**user, "authVersion": version}, response)
    return {"message": "Your password was changed. Other devices were signed out."}


@app.post("/api/admin/auth/login")
async def admin_login(payload: LoginInput, request: Request, response: Response):
    require_frontend_origin(request)
    return await create_user_login(
        response,
        email=str(payload.email),
        password=payload.password,
        admin=True,
        request=request,
    )


@app.post("/api/admin/auth/email/request")
async def request_admin_email_verification(payload: LoginInput, request: Request):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    if not is_configured_admin_email(email):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    user = await find_user_by_email(email)
    if not user or not user.get("active", True) or user.get("role") not in VALID_ROLES:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    try:
        password_ok, _ = PASSWORD_HASHER.verify_and_update(payload.password, user.get("passwordHash", ""))
    except (UnknownHashError, ValueError, TypeError):
        password_ok = False
    if not password_ok:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if user.get("emailVerified"):
        return {"verified": True, "message": "This email address is already verified."}
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest, expires = issue_otp(email, "admin-verify", code)
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"adminEmailOtpHash": digest, "adminEmailOtpExpiresAt": expires, "updatedAt": now_utc()}},
    )
    await send_email_code(email, code, "admin-verify")
    return {"verified": False, "message": "If verification is needed, a code will be sent to your email address."}


@app.post("/api/admin/auth/email/verify")
async def verify_admin_email(payload: EmailCodeInput, request: Request):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    if not is_configured_admin_email(email):
        raise HTTPException(status_code=400, detail="The verification code is invalid or expired.")
    user = await find_user_by_email(email)
    if not user or user.get("role") not in VALID_ROLES or user.get("emailVerified"):
        raise HTTPException(status_code=400, detail="The verification code is invalid or expired.")
    saved_digest = user.get("adminEmailOtpHash")
    expires_at = user.get("adminEmailOtpExpiresAt")
    if not otp_matches(email, "admin-verify", payload.code, saved_digest, expires_at):
        raise HTTPException(status_code=400, detail="The verification code is invalid or expired.")
    verified_user = await db.users.find_one_and_update(
        {
            "_id": user["_id"],
            "role": {"$in": list(VALID_ROLES)},
            "active": {"$ne": False},
            "emailVerified": {"$ne": True},
            "adminEmailOtpHash": saved_digest,
            "adminEmailOtpExpiresAt": {"$gt": now_utc()},
        },
        {
            "$set": {"emailVerified": True, "updatedAt": now_utc()},
            "$unset": {"adminEmailOtpHash": "", "adminEmailOtpExpiresAt": ""},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not verified_user:
        raise HTTPException(status_code=400, detail="The verification code is invalid or expired.")
    return {"verified": True}


@app.post("/api/admin/auth/password/request")
async def request_admin_password_reset(payload: EmailInput, request: Request):
    require_frontend_origin(request)
    if not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM"):
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin email delivery is not configured. Set SMTP_HOST and SMTP_FROM "
                "in server/.env, plus SMTP_USERNAME and SMTP_PASSWORD if your mail "
                "relay requires authentication, then restart the API."
            ),
        )
    email = normalized_email(str(payload.email))
    if not is_configured_admin_email(email):
        return {"message": "If an active admin account matches that email, a password reset code will be sent."}
    user = await find_user_by_email(email)
    if user and user.get("active", True) and user.get("role") in VALID_ROLES:
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest, expires = issue_otp(email, "admin-password-reset", code)
        await db.users.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "adminPasswordResetOtpHash": digest,
                    "adminPasswordResetOtpExpiresAt": expires,
                    "updatedAt": now_utc(),
                }
            },
        )
        await send_email_code(email, code, "admin-password-reset")
    return {"message": "If an active admin account matches that email, a password reset code will be sent."}


@app.post("/api/admin/auth/password/reset")
async def reset_admin_password(payload: AdminPasswordResetInput, request: Request):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    if not is_configured_admin_email(email):
        raise HTTPException(status_code=400, detail="The password reset code is invalid or expired.")
    user = await find_user_by_email(email)
    saved_digest = user.get("adminPasswordResetOtpHash") if user else None
    expires_at = user.get("adminPasswordResetOtpExpiresAt") if user else None
    if (
        not user
        or not user.get("active", True)
        or user.get("role") not in VALID_ROLES
        or not otp_matches(email, "admin-password-reset", payload.code, saved_digest, expires_at)
    ):
        raise HTTPException(status_code=400, detail="The password reset code is invalid or expired.")
    updated_user = await db.users.find_one_and_update(
        {
            "_id": user["_id"],
            "role": {"$in": list(VALID_ROLES)},
            "active": {"$ne": False},
            "adminPasswordResetOtpHash": saved_digest,
            "adminPasswordResetOtpExpiresAt": {"$gt": now_utc()},
        },
        {
            "$set": {"passwordHash": PASSWORD_HASHER.hash(payload.password), "updatedAt": now_utc()},
            "$inc": {"authVersion": 1},
            "$unset": {
                "adminPasswordResetOtpHash": "",
                "adminPasswordResetOtpExpiresAt": "",
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise HTTPException(status_code=400, detail="The password reset code is invalid or expired.")
    await db.auth_sessions.delete_many({"user": user["_id"]})
    return {"message": "Your password was reset. Sign in with your new password."}


@app.post("/api/admin/auth/email/change/request")
async def request_admin_email_change(
    payload: AdminEmailChangeInput,
    request: Request,
    user: dict[str, Any] = Depends(require_admin_mutation),
):
    email = normalized_email(str(payload.email))
    if not is_configured_admin_email(email):
        raise HTTPException(status_code=400, detail="The configured admin email address cannot be changed.")
    if email == normalized_email(decrypt_text(user.get("email", ""))):
        raise HTTPException(status_code=400, detail="Choose a different email address.")
    try:
        password_ok, _ = PASSWORD_HASHER.verify_and_update(payload.password, user.get("passwordHash", ""))
    except (UnknownHashError, ValueError, TypeError):
        password_ok = False
    if not password_ok:
        raise HTTPException(status_code=401, detail="Password is incorrect.")
    if await find_user_by_email(email):
        raise HTTPException(status_code=409, detail="That email address is already assigned to an account.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    digest, expires = issue_otp(email, "admin-email-change", code)
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "pendingAdminEmail": encrypt_text(email),
                "pendingAdminEmailHash": email_index(email),
                "pendingAdminEmailOtpHash": digest,
                "pendingAdminEmailOtpExpiresAt": expires,
                "updatedAt": now_utc(),
            }
        },
    )
    await send_email_code(email, code, "admin-email-change")
    await audit(user, "request-email-change", "user", str(user["_id"]), ip=request_ip(request))
    return {"message": "A verification code has been sent to the new email address."}


@app.post("/api/admin/auth/email/change/verify")
async def verify_admin_email_change(
    payload: EmailVerificationCodeInput,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(require_admin_mutation),
):
    pending_email = decrypt_text(user.get("pendingAdminEmail", ""))
    if not is_configured_admin_email(pending_email):
        raise HTTPException(status_code=400, detail="The configured admin email address cannot be changed.")
    digest = user.get("pendingAdminEmailOtpHash")
    expires = user.get("pendingAdminEmailOtpExpiresAt")
    if (
        not pending_email
        or not digest
        or not otp_matches(pending_email, "admin-email-change", payload.code, digest, expires)
    ):
        raise HTTPException(status_code=400, detail="The email change code is invalid or expired.")

    updated_user = await db.users.find_one_and_update(
        {
            "_id": user["_id"],
            "pendingAdminEmailHash": email_index(pending_email),
            "pendingAdminEmailOtpHash": digest,
            "pendingAdminEmailOtpExpiresAt": {"$gt": now_utc()},
        },
        {
            "$set": {
                "email": encrypt_text(pending_email),
                "emailHash": email_index(pending_email),
                "emailVerified": True,
                "authVersion": user.get("authVersion", 0) + 1,
                "updatedAt": now_utc(),
            },
            "$unset": {
                "pendingAdminEmail": "",
                "pendingAdminEmailHash": "",
                "pendingAdminEmailOtpHash": "",
                "pendingAdminEmailOtpExpiresAt": "",
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise HTTPException(status_code=400, detail="The email change code is invalid or expired.")
    await db.auth_sessions.delete_many({"user": user["_id"]})
    await audit(user, "change-email", "user", str(user["_id"]), ip=request_ip(request))
    clear_session_cookie(response, admin=True)
    return {"message": "Email address updated. Sign in again with your new email."}


@app.post("/api/admin/auth/password/change")
async def change_admin_password(
    payload: AdminPasswordChangeInput,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(require_admin_mutation),
):
    try:
        password_ok, _ = PASSWORD_HASHER.verify_and_update(
            payload.currentPassword,
            user.get("passwordHash", ""),
        )
    except (UnknownHashError, ValueError, TypeError):
        password_ok = False
    if not password_ok:
        raise HTTPException(status_code=401, detail="Password is incorrect.")

    updated_user = await db.users.find_one_and_update(
        {"_id": user["_id"], "authVersion": user.get("authVersion", 0)},
        {
            "$set": {
                "passwordHash": PASSWORD_HASHER.hash(payload.newPassword),
                "updatedAt": now_utc(),
            },
            "$inc": {"authVersion": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not updated_user:
        raise HTTPException(status_code=409, detail="Account security settings changed. Sign in again and retry.")
    await db.auth_sessions.delete_many({"user": user["_id"]})
    await audit(user, "change-password", "user", str(user["_id"]), ip=request_ip(request))
    clear_session_cookie(response, admin=True)
    return {"message": "Password changed. Sign in again."}


@app.post("/api/admin/auth/logout", status_code=204)
async def logout(request: Request, response: Response):
    require_frontend_origin(request)
    for token in (request.cookies.get("store_admin", ""), request.cookies.get("store_session", "")):
        if not token:
            continue
        try:
            claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"require": ["jti"]})
            session_hash = hashlib.sha256(claims["jti"].encode("utf-8")).hexdigest()
            await db.auth_sessions.delete_one({"tokenHash": session_hash})
        except jwt.InvalidTokenError:
            pass
    clear_session_cookie(response, admin=True)
    clear_session_cookie(response, admin=False)
    # The injected Response has no status of its own; without this the server fails to send it.
    response.status_code = 204
    return response


@app.get("/api/books")
async def public_books():
    projection = {"title": 1, "subtitle": 1, "description": 1, "image": 1, "format": 1, "year": 1, "status": 1, "createdAt": 1, "updatedAt": 1}
    query = {"$or": [{"status": "published"}, {"status": {"$exists": False}}]}
    return {"books": [serialize(book) for book in await db.books.find(query, projection).sort("createdAt", -1).to_list(500)]}


STORE_BOOK_PROJECTION = {
    "title": 1, "subtitle": 1, "description": 1, "image": 1, "format": 1,
    "year": 1, "category": 1, "priceNpr": 1, "stock": 1, "createdAt": 1,
}
PUBLISHED_BOOK_QUERY = {"$or": [{"status": "published"}, {"status": {"$exists": False}}]}


def store_book_view(book: dict[str, Any]) -> dict[str, Any]:
    stock = book.get("stock", 0)
    safe_stock = max(0, stock) if isinstance(stock, int) and not isinstance(stock, bool) else 0
    return serialize({**book, "stock": safe_stock})


def category_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:80]


async def ordered_store_categories(books: list[dict[str, Any]]) -> list[str]:
    in_use = {book.get("category") or book.get("format") or "Books" for book in books}
    managed = await db[CATEGORY_COLLECTION].find({"active": {"$ne": False}}, {"name": 1}).sort([("sortOrder", 1), ("name", 1)]).to_list(200)
    ordered = [row["name"] for row in managed if row.get("name") in in_use]
    return ordered + sorted(in_use - set(ordered))


@app.get("/api/store/books")
async def store_books():
    rows = await db.books.find(PUBLISHED_BOOK_QUERY, STORE_BOOK_PROJECTION).sort("createdAt", -1).limit(500).to_list(500)
    books = [store_book_view(book) for book in rows]
    return {"books": books, "categories": await ordered_store_categories(books)}


@app.get("/api/store/books/{book_id}")
async def store_book_detail(book_id: str):
    oid = require_object_id(book_id, "book")
    book = await db.books.find_one({"_id": oid, **PUBLISHED_BOOK_QUERY}, STORE_BOOK_PROJECTION)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found.")
    category = book.get("category") or book.get("format")
    related_query: dict[str, Any] = {"_id": {"$ne": oid}, **PUBLISHED_BOOK_QUERY}
    if category:
        related_query["$and"] = [{"$or": [{"category": category}, {"format": category}]}]
    related = await db.books.find(related_query, STORE_BOOK_PROJECTION).sort("createdAt", -1).limit(4).to_list(4)
    if len(related) < 4:
        seen = [oid, *(row["_id"] for row in related)]
        related += await db.books.find({"_id": {"$nin": seen}, **PUBLISHED_BOOK_QUERY}, STORE_BOOK_PROJECTION).sort("createdAt", -1).limit(4 - len(related)).to_list(4)
    return {"book": store_book_view(book), "related": [store_book_view(row) for row in related]}


@app.get("/api/site/status")
async def site_status():
    state = await maintenance_state()
    result: dict[str, Any] = {"maintenance": state["enabled"]}
    if state["enabled"]:
        until = state["until"]
        content = await db[CONTENT_COLLECTION].find_one({"key": "author-profile", "public": True}, {"value": 1}) or {}
        profile = content.get("value") if isinstance(content.get("value"), dict) else {}
        store = await db[SETTINGS_COLLECTION].find_one({"_id": "store"}, {"contactEmail": 1}) or {}
        # Profile name/email are encrypted at rest like other personal fields.
        name = decrypt_text(profile.get("name", "")) if isinstance(profile.get("name"), str) else ""
        email = decrypt_text(profile.get("email", "")) if isinstance(profile.get("email"), str) else ""
        result.update({
            "message": state["message"],
            "until": serialize(until) if until and until > now_utc() else None,
            "authorName": name,
            "contactEmail": decrypt_text(store.get("contactEmail", "")) or email,
        })
    return result


@app.get("/api/admin/maintenance", dependencies=[Depends(require_permission("settings:read"))])
async def admin_maintenance():
    state = await maintenance_state(force=True)
    return {"maintenance": {
        "enabled": state["enabled"],
        "message": state["message"],
        "until": serialize(state["until"]),
        "updatedAt": serialize(state["updatedAt"]),
    }}


@app.put("/api/admin/maintenance")
async def update_maintenance(payload: MaintenanceInput, request: Request, user: dict[str, Any] = Depends(require_permission("settings:write"))):
    until = payload.until
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    await db[SETTINGS_COLLECTION].update_one(
        {"_id": "maintenance"},
        {"$set": {"enabled": payload.enabled, "message": payload.message, "until": until, "updatedAt": now_utc(), "updatedBy": user["_id"]}},
        upsert=True,
    )
    state = await maintenance_state(force=True)
    await audit(user, "maintenance-on" if payload.enabled else "maintenance-off", "settings", "maintenance", ip=request_ip(request))
    return {"maintenance": {"enabled": state["enabled"], "message": state["message"], "until": serialize(state["until"]), "updatedAt": serialize(state["updatedAt"])}}


@app.get("/api/store/settings")
async def store_settings():
    settings = await db[SETTINGS_COLLECTION].find_one({"_id": "store"}) or {}
    bank_account_number = decrypt_text(settings.get("bankAccountNumber", ""))
    return {
        "settings": {
            "storeName": settings.get("storeName", "Author Bookstore"),
            "contactEmail": decrypt_text(settings.get("contactEmail", "")),
            "bankName": settings.get("bankName", ""),
            "bankAccountName": settings.get("bankAccountName", ""),
            "bankAccountNumber": bank_account_number,
            "bankBranch": settings.get("bankBranch", ""),
            "bankInstructions": settings.get("bankInstructions", ""),
            "bankTransferEnabled": bool(settings.get("bankName") and settings.get("bankAccountName") and bank_account_number),
            "esewaEnabled": bool(payment_secret("esewa", provider_mode("esewa")) and os.getenv(f'ESEWA_{provider_mode("esewa").upper()}_PRODUCT_CODE')),
            "khaltiEnabled": bool(payment_secret("khalti", provider_mode("khalti"))),
        }
    }


async def public_reviews():
    rows = await db.reviews.find({"status": "approved"}).sort("createdAt", -1).limit(100).to_list(100)
    for review in rows:
        book = await db.books.find_one({"_id": review.get("book")}, {"title": 1})
        if book:
            review["book"] = {"_id": str(book["_id"]), "title": book["title"]}
    return {"reviews": [serialize(row) for row in rows]}


@app.get("/api/gallery")
async def public_gallery():
    rows = await db[MEDIA_COLLECTION].find(
        {"public": True, "category": "gallery"},
        {"title": 1, "url": 1, "altText": 1, "category": 1, "createdAt": 1},
    ).sort("createdAt", -1).limit(200).to_list(200)
    return {"images": [serialize(row) for row in rows]}


@app.get("/api/content")
async def public_content():
    rows = await db[CONTENT_COLLECTION].find({"public": True}, {"key": 1, "value": 1}).to_list(500)
    return {"content": [serialize(row) for row in rows]}


@app.post("/api/newsletter/subscribe")
async def subscribe_to_newsletter(payload: NewsletterSubscribeInput, request: Request):
    require_frontend_origin(request)
    email = normalized_email(str(payload.email))
    try:
        await db[NEWSLETTER_COLLECTION].update_one(
            {"emailHash": email_index(email)},
            {
                "$setOnInsert": {
                    "email": encrypt_text(email),
                    "emailHash": email_index(email),
                    "subscribedAt": now_utc(),
                    "active": True,
                }
            },
            upsert=True,
        )
    except DuplicateKeyError:
        return {"subscribed": True, "message": "Thanks for subscribing."}
    return {"subscribed": True, "message": "Thanks for subscribing."}


async def create_notification(kind: str, title: str, message: str, order_id: ObjectId | None = None) -> None:
    # Dashboard notifications are best-effort: they must never undo an order or payment.
    try:
        await db[NOTIFICATION_COLLECTION].insert_one({
            "kind": kind,
            "title": title[:160],
            "message": message[:500],
            "order": order_id,
            "read": False,
            "createdAt": now_utc(),
        })
    except PyMongoError:
        logger.warning("Admin notification could not be recorded (%s).", kind)


def history_entry(status: str, note: str = "", **extra: Any) -> dict[str, Any]:
    return {"status": status, "note": note, "at": now_utc(), **extra}


async def notify_low_stock(items: list[dict[str, Any]]) -> None:
    settings = await db[SETTINGS_COLLECTION].find_one({"_id": "store"}) or {}
    threshold = settings.get("lowStockThreshold", 5)
    for item in items:
        book = await db.books.find_one({"_id": item["book"]}, {"title": 1, "stock": 1})
        stock = book.get("stock") if book else None
        # Alert only when this order moved the book across the threshold, not on every later sale.
        if isinstance(stock, int) and stock <= threshold < stock + item["quantity"]:
            await create_notification(
                "low_stock",
                f'Low stock: {book.get("title", "Book")}',
                "Sold out — restock to keep it available." if stock == 0 else f"{stock} left in stock.",
            )


async def reserve_order(payload: CheckoutInput, provider: str, mode: str, account: dict[str, Any] | None = None) -> dict[str, Any]:
    # A signed-in customer always orders under their verified account email.
    email = normalized_email(decrypt_text(account["email"])) if account else normalized_email(str(payload.customer.email))
    quantities: dict[ObjectId, int] = defaultdict(int)
    for item in payload.items:
        quantities[ObjectId(item.bookId)] += item.quantity
    books = await db.books.find({
        "_id": {"$in": list(quantities)},
        "$or": [{"status": "published"}, {"status": {"$exists": False}}],
    }).to_list(len(quantities))
    if len(books) != len(quantities):
        raise HTTPException(status_code=400, detail="One or more books are no longer available.")
    order_items: list[dict[str, Any]] = []
    total = 0.0
    currency = "npr"
    for book in books:
        quantity = quantities[book["_id"]]
        price = book.get("priceNpr")
        if (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or price <= 0
            or price > 10_000_000
            or not math.isfinite(price)
        ):
            raise HTTPException(status_code=400, detail=f'"{book.get("title", "Book")}" does not have a Nepalese rupee price configured.')
        stock = book.get("stock", 0)
        if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
            raise HTTPException(status_code=400, detail=f'Inventory for "{book.get("title", "Book")}" must be configured as a whole number.')
        if stock < quantity:
            raise HTTPException(status_code=409, detail=f'Not enough inventory for "{book.get("title", "Book")}".')
        total += float(price) * quantity
        order_items.append({"book": book["_id"], "title": book["title"], "quantity": quantity, "unitPrice": float(price)})
    total = round(total + 1e-8, 2)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Order total must be greater than zero.")
    stamp = now_utc()
    customer_data = {
        "name": payload.customer.name.strip(),
        "email": email,
        "address": payload.customer.address.strip(),
        "phone": payload.customer.phone.strip(),
    }
    existing_customer = await db.customers.find_one({"$or": [{"emailHash": email_index(email)}, {"email": email}]})
    encrypted_customer = encrypt_fields({**customer_data, "emailHash": email_index(email), "updatedAt": stamp})
    if existing_customer:
        await db.customers.update_one({"_id": existing_customer["_id"]}, {"$set": encrypted_customer})
        customer_record = await db.customers.find_one({"_id": existing_customer["_id"]})
    else:
        created_customer = {**encrypted_customer, "createdAt": stamp}
        customer_id = (await db.customers.insert_one(created_customer)).inserted_id
        customer_record = await db.customers.find_one({"_id": customer_id})
    tracking_token = secrets.token_urlsafe(32)
    order = {
        "customer": encrypt_fields(customer_data),
        "customerRecord": customer_record["_id"],
        "trackingTokenHash": hashlib.sha256(tracking_token.encode("utf-8")).hexdigest(),
        "items": order_items,
        "currency": currency,
        "total": total,
        "status": "pending",
        "paymentProvider": provider,
        "paymentReference": "",
        "paymentStatus": "pending",
        "paymentMode": mode,
        "stockDeducted": False,
        **({"user": account["_id"]} if account else {}),
        "statusHistory": [{"status": "pending", "note": "Order placed", "at": stamp}],
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    order_result = await db.orders.insert_one(order)
    order["_id"] = order_result.inserted_id
    deducted: list[dict[str, Any]] = []
    try:
        for item in order_items:
            changed = await db.books.update_one(
                {"_id": item["book"], "stock": {"$gte": item["quantity"]}},
                {"$inc": {"stock": -item["quantity"]}, "$set": {"updatedAt": now_utc()}},
            )
            if changed.modified_count != 1:
                raise HTTPException(status_code=409, detail=f'Not enough inventory for "{item["title"]}".')
            deducted.append(item)
        await db.orders.update_one({"_id": order["_id"]}, {"$set": {"stockDeducted": True, "updatedAt": now_utc()}})
    except Exception:
        for item in deducted:
            await db.books.update_one({"_id": item["book"]}, {"$inc": {"stock": item["quantity"]}})
        await db.orders.delete_one({"_id": order["_id"]})
        raise
    try:
        await notify_low_stock(order_items)
    except PyMongoError:
        logger.warning("Low-stock check failed after reserving order %s.", order["_id"])
    order["stockDeducted"] = True
    order["trackingToken"] = tracking_token
    return order


async def send_store_email(email: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    if not host or not sender:
        logger.warning("Store email notification skipped because SMTP is not configured.")
        return False
    if bool(username) != bool(password):
        logger.error("Store email notification skipped because SMTP authentication is incomplete.")
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = email
    message.set_content(body)

    def deliver() -> None:
        port = int(os.getenv("SMTP_PORT", "587"))
        smtp_client = smtplib.SMTP_SSL if SMTP_SECURITY == "ssl" else smtplib.SMTP
        with smtp_client(host, port, timeout=10) as smtp:
            if SMTP_SECURITY == "starttls":
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)

    try:
        await asyncio.to_thread(deliver)
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        logger.warning("Store email notification failed (%s).", type(exc).__name__)
        return False
    return True


async def notify_order_placed(order: dict[str, Any]) -> None:
    email = normalized_email(decrypt_text(order.get("customer", {}).get("email", "")))
    order_id = str(order["_id"])
    titles = ", ".join(item["title"] for item in order.get("items", []))
    summary = (
        f"Order {order_id} has been received.\n"
        f"Items: {titles}\n"
        f"Total: NPR {order['total']:.2f}\n"
        "Payment status: awaiting confirmation.\n"
        "You will receive another message after your payment is confirmed."
    )
    await send_store_email(email, f"Order received — {order_id}", summary)
    method = {"esewa": "eSewa", "khalti": "Khalti", "bank_transfer": "bank transfer"}.get(order.get("paymentProvider", ""), "online payment")
    await create_notification(
        "order",
        f"New order · NPR {order['total']:,.2f}",
        f"{decrypt_text(order.get('customer', {}).get('name', 'A customer'))} ordered {titles} via {method}.",
        order["_id"],
    )
    admin_email = normalized_email(os.getenv("ADMIN_EMAIL", ""))
    if admin_email and admin_email != email:
        await send_store_email(
            admin_email,
            f"New bookstore order — {order_id}",
            f"A new order is awaiting payment confirmation.\n{summary}",
        )


async def notify_payment_confirmed(order: dict[str, Any]) -> None:
    email = normalized_email(decrypt_text(order.get("customer", {}).get("email", "")))
    order_id = str(order["_id"])
    titles = ", ".join(item["title"] for item in order.get("items", []))
    await send_store_email(
        email,
        f"Payment confirmed — {order_id}",
        (
            f"Payment for order {order_id} has been confirmed.\n"
            f"Items: {titles}\n"
            f"Total: NPR {order['total']:.2f}\n"
            "Your order is now being prepared."
        ),
    )
    await create_notification(
        "payment",
        f"Payment confirmed · NPR {order['total']:,.2f}",
        f"Order {order_id} is paid and ready to prepare.",
        order["_id"],
    )


ORDER_STATUS_LABELS = {"fulfilled": "delivered"}


async def notify_order_status(order: dict[str, Any], note: str = "") -> None:
    email = normalized_email(decrypt_text(order.get("customer", {}).get("email", "")))
    order_id = str(order["_id"])
    titles = ", ".join(item["title"] for item in order.get("items", []))
    lines = [
        f"Order {order_id} is now {ORDER_STATUS_LABELS.get(order['status'], order['status'])}.",
        f"Items: {titles}",
        f"Payment status: {order['paymentStatus']}.",
    ]
    if order["status"] == "shipped" and order.get("trackingNumber"):
        lines.append(f"Tracking: {order.get('carrier') or 'Courier'} {order['trackingNumber']}")
    if note:
        lines.append(f"Note from the bookstore: {note}")
    await send_store_email(email, f"Order update — {order_id}", "\n".join(lines))


async def release_inventory(order: dict[str, Any] | None, note: str = "") -> None:
    if not order:
        return
    claimed = await db.orders.find_one_and_update(
        {"_id": order["_id"], "stockDeducted": True, "status": "pending"},
        {
            "$set": {"stockDeducted": False, "status": "cancelled", "paymentStatus": "failed", "updatedAt": now_utc()},
            "$push": {"statusHistory": history_entry("cancelled", note or "Payment was not completed; reserved stock was released.")},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not claimed:
        return
    for item in claimed.get("items", []):
        await db.books.update_one({"_id": item["book"]}, {"$inc": {"stock": item["quantity"]}})
    await db.payments.update_many({"order": claimed["_id"], "status": {"$in": ["initiated", "pending"]}}, {"$set": {"status": "failed", "updatedAt": now_utc()}})


async def complete_payment(order: dict[str, Any], provider: str, transaction_id: str) -> None:
    paid = await db.orders.find_one_and_update(
        {"_id": order["_id"], "status": "pending", "paymentProvider": provider, "stockDeducted": True},
        {
            "$set": {"status": "paid", "paymentStatus": "paid", "paymentReference": encrypt_text(transaction_id), "updatedAt": now_utc()},
            "$push": {"statusHistory": history_entry("paid", f"Payment verified with {provider.title()}.")},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not paid and order.get("paymentStatus") != "paid":
        raise HTTPException(status_code=409, detail="Order is no longer awaiting payment.")
    if paid:
        await notify_payment_confirmed(paid)
    await db.payments.update_one(
        {"order": order["_id"], "provider": provider, "status": {"$in": ["initiated", "pending", "completed"]}},
        {"$set": {"status": "completed", "providerTransactionId": encrypt_text(transaction_id), "verifiedAt": now_utc(), "lastCheckedAt": now_utc(), "updatedAt": now_utc()}},
    )


def provider_mode(provider: str) -> str:
    return "live" if os.getenv(f"{provider.upper()}_MODE", "test").lower() == "live" else "test"


def payment_secret(provider: str, mode: str) -> str:
    return os.getenv(f"{provider.upper()}_{mode.upper()}_SECRET_KEY", "")


def payment_origin(provider: str, mode: str) -> str:
    if provider == "esewa":
        return "https://epay.esewa.com.np" if mode == "live" else "https://rc-epay.esewa.com.np"
    return "https://khalti.com" if mode == "live" else "https://dev.khalti.com"


def require_public_https(value: str, label: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.hostname in {"localhost", "127.0.0.1"}:
        raise HTTPException(status_code=503, detail=f"{label} must be a public HTTPS URL when live payments are enabled.")


def esewa_status_url(order: dict[str, Any], product_code: str) -> str:
    origin = "https://esewa.com.np" if order.get("paymentMode") == "live" else "https://rc.esewa.com.np"
    query = urlencode({
        "product_code": product_code,
        "total_amount": f'{order["total"]:.2f}',
        "transaction_uuid": str(order["_id"]),
    })
    return f"{origin}/api/epay/transaction/status/?{query}"


def esewa_amount_matches(value: Any, expected: float) -> bool:
    try:
        amount = float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return False
    return round(amount * 100) == round(expected * 100)


def provider_json(response: httpx.Response) -> dict[str, Any]:
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Payment provider returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Payment provider returned an invalid response.")
    if not response.is_success:
        raise HTTPException(status_code=502, detail="Payment provider could not complete the request.")
    return result


def validate_khalti_lookup(result: dict[str, Any], status_code: int, pidx: str, amount: float) -> dict[str, Any]:
    normalized = str(result.get("status", "")).strip().lower()
    statuses = {
        "completed": "Completed",
        "pending": "Pending",
        "initiated": "Initiated",
        "user canceled": "User canceled",
        "expired": "Expired",
        "refunded": "Refunded",
        "partially refunded": "Partially Refunded",
    }
    if status_code < 200 or status_code >= 300:
        if normalized not in {"user canceled", "expired"}:
            raise HTTPException(status_code=502, detail="Khalti payment lookup could not be completed.")
    try:
        paid_amount = int(result.get("total_amount"))
    except (ValueError, TypeError):
        paid_amount = -1
    if isinstance(result.get("total_amount"), bool) or result.get("pidx") != pidx or paid_amount != round(amount * 100):
        raise HTTPException(status_code=400, detail="Khalti payment details do not match this order.")
    if normalized not in statuses:
        raise HTTPException(status_code=502, detail="Khalti returned an unrecognized payment status.")
    result["status"] = statuses[normalized]
    return result


async def lookup_khalti(pidx: str, amount: float, mode: str) -> dict[str, Any]:
    secret = payment_secret("khalti", mode)
    if not secret:
        raise HTTPException(status_code=503, detail="Khalti credentials for the selected mode are not configured.")
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            response = await client.post(
                f'{payment_origin("khalti", mode)}/api/v2/epayment/lookup/',
                headers={"Authorization": f"Key {secret}", "Content-Type": "application/json"},
                json={"pidx": pidx},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Khalti payment lookup could not be completed.") from exc
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Khalti payment lookup returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Khalti payment lookup returned an invalid response.")
    return validate_khalti_lookup(result, response.status_code, pidx, amount)


async def verify_khalti_payment(payment: dict[str, Any], order: dict[str, Any]) -> dict[str, Any]:
    pidx = decrypt_text(payment.get("providerReference", ""))
    if not pidx:
        raise HTTPException(status_code=503, detail="Khalti payment reference is missing.")
    result = await lookup_khalti(pidx, float(payment["amount"]), payment.get("mode", "test"))
    if order.get("paymentProvider") != "khalti":
        raise HTTPException(status_code=409, detail="Khalti payment does not match its stored order.")
    transaction_id = result.get("transaction_id") or result.get("tidx") or pidx
    reference = decrypt_text(order.get("paymentReference", ""))
    if reference not in {pidx, transaction_id}:
        raise HTTPException(status_code=409, detail="Khalti payment does not match its stored order.")
    if result["status"] == "Completed":
        await complete_payment(order, "khalti", transaction_id)
    elif result["status"] in {"User canceled", "Expired"}:
        await release_inventory(order)
    elif result["status"] in {"Refunded", "Partially Refunded"} and order.get("paymentStatus") == "paid":
        await db.orders.update_one({"_id": order["_id"]}, {"$set": {"paymentStatus": "refunded", "updatedAt": now_utc()}})
    payment_status = (
        "completed" if result["status"] == "Completed" else
        "pending" if result["status"] in {"Pending", "Initiated"} else
        "refunded" if result["status"] in {"Refunded", "Partially Refunded"} else "failed"
    )
    await db.payments.update_one({"_id": payment["_id"]}, {"$set": {"status": payment_status, "lastCheckedAt": now_utc(), "updatedAt": now_utc()}})
    updated = await db.payments.find_one({"_id": payment["_id"]})
    return updated or payment


async def verify_esewa_payment(payment: dict[str, Any], order: dict[str, Any]) -> dict[str, Any]:
    mode = payment.get("mode", "test")
    product_code = os.getenv(f"ESEWA_{mode.upper()}_PRODUCT_CODE", "")
    if not product_code:
        raise HTTPException(status_code=503, detail="eSewa product code for the selected mode is not configured.")
    transaction_uuid = decrypt_text(payment.get("providerReference", ""))
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            response = await client.get(esewa_status_url(order, product_code))
            result = provider_json(response)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="eSewa payment lookup could not be completed.") from exc
    if str(result.get("transaction_uuid")) != str(order["_id"]) or not esewa_amount_matches(result.get("total_amount"), float(payment["amount"])) or result.get("product_code") != product_code:
        raise HTTPException(status_code=400, detail="eSewa transaction details do not match this order.")
    if result.get("status") == "COMPLETE":
        await complete_payment(order, "esewa", str(result.get("transaction_code") or transaction_uuid))
        status = "completed"
    elif result.get("status") in {"PENDING", "AMBIGUOUS"}:
        status = "pending"
    elif result.get("status") in {"FULL_REFUND", "CANCELED", "NOT_FOUND"}:
        await release_inventory(order)
        status = "refunded" if result.get("status") == "FULL_REFUND" else "failed"
    else:
        raise HTTPException(status_code=502, detail="eSewa returned an unrecognized payment status.")
    await db.payments.update_one({"_id": payment["_id"]}, {"$set": {"status": status, "lastCheckedAt": now_utc(), "updatedAt": now_utc()}})
    return await db.payments.find_one({"_id": payment["_id"]}) or payment


async def start_nepal_payment(payload: CheckoutInput, provider: str, account: dict[str, Any] | None = None) -> dict[str, Any]:
    mode = provider_mode(provider)
    secret = payment_secret(provider, mode)
    if not secret:
        raise HTTPException(status_code=503, detail=f"{provider.title()} credentials for the selected mode are not configured.")
    product_code = os.getenv(f"ESEWA_{mode.upper()}_PRODUCT_CODE", "") if provider == "esewa" else ""
    if provider == "esewa" and not product_code:
        raise HTTPException(status_code=503, detail="eSewa product code for the selected mode is not configured.")
    if mode == "live":
        require_public_https(API_PUBLIC_URL, "API_PUBLIC_URL")
        require_public_https(FRONTEND_URL, "FRONTEND_URL")
        if provider == "khalti":
            require_public_https(WEBSITE_URL, "PUBLIC_WEBSITE_URL")
    order = await reserve_order(payload, provider, mode, account)
    stamp = now_utc()
    payment = {
        "order": order["_id"],
        "provider": provider,
        "mode": mode,
        "currency": "npr",
        "amount": order["total"],
        "providerReference": "",
        "status": "initiated",
        "metadata": {},
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    payment_result = await db.payments.insert_one(payment)
    payment["_id"] = payment_result.inserted_id
    callback = f'{API_PUBLIC_URL}/api/payments/nepal/{provider}/callback?orderId={order["_id"]}&trackingToken={order["trackingToken"]}'
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            if provider == "khalti":
                response = await client.post(
                    f'{payment_origin(provider, mode)}/api/v2/epayment/initiate/',
                    headers={"Authorization": f"Key {secret}", "Content-Type": "application/json"},
                    json={
                        "return_url": callback,
                        "website_url": WEBSITE_URL,
                        "amount": round(order["total"] * 100),
                        "purchase_order_id": str(order["_id"]),
                        "purchase_order_name": ", ".join(item["title"] for item in order["items"])[:100],
                        "customer_info": {
                            "name": payload.customer.name,
                            "email": normalized_email(str(payload.customer.email)),
                            **({"phone": payload.customer.phone} if payload.customer.phone else {}),
                        },
                        "product_details": [{
                            "identity": str(item["book"]),
                            "name": item["title"],
                            "total_price": round(item["unitPrice"] * item["quantity"] * 100),
                            "quantity": item["quantity"],
                            "unit_price": round(item["unitPrice"] * 100),
                        } for item in order["items"]],
                    },
                )
                result = provider_json(response)
                if not result.get("pidx") or not result.get("payment_url"):
                    raise HTTPException(status_code=502, detail="Khalti did not return a valid payment session.")
                reference = str(result["pidx"])
                await db.payments.update_one({"_id": payment["_id"]}, {"$set": {"providerReference": encrypt_text(reference), "status": "pending", "updatedAt": now_utc()}})
                await db.orders.update_one({"_id": order["_id"]}, {"$set": {"paymentReference": encrypt_text(reference), "updatedAt": now_utc()}})
                await notify_order_placed(order)
                return {"orderId": str(order["_id"]), "paymentUrl": result["payment_url"], "mode": mode}
            total = f'{order["total"]:.2f}'
            fields = {
                "amount": total,
                "tax_amount": "0",
                "total_amount": total,
                "transaction_uuid": str(order["_id"]),
                "product_code": product_code,
                "product_service_charge": "0",
                "product_delivery_charge": "0",
                "success_url": callback,
                "failure_url": f"{callback}&result=failed",
            }
            signed_fields = "total_amount,transaction_uuid,product_code"
            signing_message = ",".join(f"{key}={fields[key]}" for key in signed_fields.split(","))
            fields["signed_field_names"] = signed_fields
            fields["signature"] = base64.b64encode(hmac.new(secret.encode("utf-8"), signing_message.encode("utf-8"), hashlib.sha256).digest()).decode("ascii")
            reference = str(order["_id"])
            await db.payments.update_one({"_id": payment["_id"]}, {"$set": {"providerReference": encrypt_text(reference), "status": "pending", "updatedAt": now_utc()}})
            await db.orders.update_one({"_id": order["_id"]}, {"$set": {"paymentReference": encrypt_text(reference), "updatedAt": now_utc()}})
            await notify_order_placed(order)
            return {"orderId": str(order["_id"]), "action": payment_origin(provider, mode) + "/api/epay/main/v2/form", "fields": fields, "mode": mode}
    except Exception:
        await release_inventory(order)
        await db.orders.delete_one({"_id": order["_id"], "status": "cancelled"})
        await db.payments.delete_one({"_id": payment["_id"]})
        raise


@app.post("/api/payments/nepal/esewa/initiate")
async def esewa_initiate(payload: CheckoutInput, request: Request):
    require_frontend_origin(request)
    return await start_nepal_payment(payload, "esewa", await customer_session(request))


@app.post("/api/payments/nepal/khalti/initiate")
async def khalti_initiate(payload: CheckoutInput, request: Request):
    require_frontend_origin(request)
    return await start_nepal_payment(payload, "khalti", await customer_session(request))


@app.post("/api/orders/bank-transfer", status_code=201)
async def create_bank_transfer_order(payload: CheckoutInput, request: Request, response: Response):
    require_frontend_origin(request)
    settings = await db[SETTINGS_COLLECTION].find_one({"_id": "store"}) or {}
    account_number = decrypt_text(settings.get("bankAccountNumber", ""))
    if not (settings.get("bankName") and settings.get("bankAccountName") and account_number):
        raise HTTPException(status_code=503, detail="Bank transfer is not available until the store configures its bank details.")

    order = await reserve_order(payload, "bank_transfer", "manual", await customer_session(request))
    order_id = str(order["_id"])
    stamp = now_utc()
    try:
        await db.payments.insert_one({
            "order": order["_id"],
            "provider": "bank_transfer",
            "mode": "manual",
            "currency": "npr",
            "amount": order["total"],
            "providerReference": encrypt_text(order_id),
            "status": "pending",
            "metadata": {},
            "createdAt": stamp,
            "updatedAt": stamp,
        })
    except PyMongoError as exc:
        await release_inventory(order)
        raise HTTPException(status_code=503, detail="The order could not be recorded. Your reserved inventory has been released.") from exc

    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {"paymentReference": encrypt_text(order_id), "updatedAt": stamp}},
    )
    response.set_cookie(
        f"payment_tracking_{order_id}",
        order["trackingToken"],
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
        path=f"/api/payments/nepal/track/{order_id}",
        max_age=24 * 60 * 60,
    )
    set_order_access_cookie(response, order_id)
    await notify_order_placed(order)
    return {"orderId": order_id, "paymentReference": order_id, "status": "pending"}


def verify_esewa_callback(data: str, order: dict[str, Any]) -> dict[str, Any]:
    try:
        decoded = base64.b64decode(data, validate=True)
        result = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="eSewa payment response is invalid.") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=400, detail="eSewa payment response is invalid.")
    fields = result.get("signed_field_names", "").split(",")
    secret = payment_secret("esewa", order.get("paymentMode", "test"))
    allowed = {"transaction_code", "status", "total_amount", "transaction_uuid", "product_code", "signed_field_names"}
    if not fields or any(field not in allowed for field in fields) or result.get("transaction_uuid") != str(order["_id"]):
        raise HTTPException(status_code=400, detail="eSewa payment signature is invalid.")
    message = ",".join(f"{field}={result.get(field, '')}" for field in fields)
    expected = base64.b64encode(hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()).decode("ascii")
    if not hmac.compare_digest(str(result.get("signature", "")), expected):
        raise HTTPException(status_code=400, detail="eSewa payment signature is invalid.")
    return result


async def get_callback_order(request: Request, provider: str) -> tuple[dict[str, Any], str]:
    order_id = request.query_params.get("orderId", "")
    token = request.query_params.get("trackingToken", "")
    if not ObjectId.is_valid(order_id) or not token or len(token) > 200:
        raise HTTPException(status_code=400, detail="Payment session is invalid or expired.")
    order = await db.orders.find_one({"_id": ObjectId(order_id), "paymentProvider": provider})
    if not order or not hmac.compare_digest(order.get("trackingTokenHash", ""), hashlib.sha256(token.encode("utf-8")).hexdigest()):
        raise HTTPException(status_code=400, detail="Payment session is invalid or expired.")
    return order, token


def redirect_payment_result(order: dict[str, Any], token: str, provider: str) -> RedirectResponse:
    destination = f"{FRONTEND_URL}/store/orders/{order['_id']}?payment=return&gateway={provider}"
    redirect = RedirectResponse(destination, status_code=303)
    redirect.set_cookie(
        f"payment_tracking_{order['_id']}",
        token,
        httponly=True,
        secure=cookie_secure(order.get("paymentMode")),
        samesite="strict",
        path=f"/api/payments/nepal/track/{order['_id']}",
        max_age=24 * 60 * 60,
    )
    set_order_access_cookie(redirect, str(order["_id"]))
    return redirect


@app.get("/api/payments/nepal/esewa/callback")
async def esewa_callback(request: Request):
    order, token = await get_callback_order(request, "esewa")
    if request.query_params.get("result") == "failed":
        await release_inventory(order)
        return redirect_payment_result(order, token, "esewa")
    encoded = request.query_params.get("data", "")
    if len(encoded) > 12000:
        raise HTTPException(status_code=400, detail="eSewa payment response is too large.")
    callback = verify_esewa_callback(encoded, order)
    payment = await db.payments.find_one({"order": order["_id"], "provider": "esewa"})
    product_code = os.getenv(f'ESEWA_{order.get("paymentMode", "test").upper()}_PRODUCT_CODE', "")
    if not payment or not product_code or callback.get("product_code") != product_code or not esewa_amount_matches(callback.get("total_amount"), float(order["total"])):
        raise HTTPException(status_code=400, detail="eSewa transaction details do not match this order.")
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            status_response = await client.get(esewa_status_url(order, product_code))
            status = provider_json(status_response)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="eSewa transaction lookup could not be completed.") from exc
    if status.get("status") == "COMPLETE" and status.get("transaction_uuid") == str(order["_id"]) and esewa_amount_matches(status.get("total_amount"), float(order["total"])) and status.get("product_code") == product_code:
        await complete_payment(order, "esewa", str(status.get("transaction_code") or callback.get("transaction_code") or order["_id"]))
    elif status.get("status") in {"CANCELED", "NOT_FOUND"}:
        await release_inventory(order)
    else:
        await db.payments.update_one({"_id": payment["_id"]}, {"$set": {"status": "pending", "lastCheckedAt": now_utc()}})
    return redirect_payment_result(order, token, "esewa")


@app.get("/api/payments/nepal/khalti/callback")
async def khalti_callback(request: Request):
    order, token = await get_callback_order(request, "khalti")
    purchase_order_id = request.query_params.get("purchase_order_id")
    if purchase_order_id and purchase_order_id != str(order["_id"]):
        raise HTTPException(status_code=400, detail="Khalti returned a payment for a different order.")
    pidx = request.query_params.get("pidx", "")
    payment = await db.payments.find_one({"order": order["_id"], "provider": "khalti"})
    if pidx and payment and hmac.compare_digest(decrypt_text(payment.get("providerReference", "")), pidx):
        await verify_khalti_payment(payment, order)
    return redirect_payment_result(order, token, "khalti")


def issue_order_access_token(order_id: str) -> str:
    return jwt.encode(
        {"sub": order_id, "typ": "order-access", "exp": now_utc() + timedelta(days=ORDER_ACCESS_DAYS)},
        JWT_SECRET,
        algorithm="HS256",
    )


def order_access_token_valid(token: str, order_id: str) -> bool:
    if not token or len(token) > 1000:
        return False
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"require": ["exp", "sub", "typ"]})
    except jwt.PyJWTError:
        return False
    return claims.get("typ") == "order-access" and hmac.compare_digest(str(claims.get("sub")), order_id)


def set_order_access_cookie(response: Response, order_id: str) -> None:
    response.set_cookie(
        f"order_access_{order_id}",
        issue_order_access_token(order_id),
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
        path=f"/api/payments/nepal/track/{order_id}",
        max_age=ORDER_ACCESS_DAYS * 24 * 60 * 60,
    )


async def tracked_order(order_id: str, request: Request) -> dict[str, Any]:
    oid = require_object_id(order_id, "order")
    order = await db.orders.find_one({"_id": oid})
    token = request.cookies.get(f"payment_tracking_{order_id}", "")
    checkout_token_valid = bool(order and token and hmac.compare_digest(
        order.get("trackingTokenHash", ""), hashlib.sha256(token.encode("utf-8")).hexdigest(),
    ))
    if order and not checkout_token_valid and not order_access_token_valid(request.cookies.get(f"order_access_{order_id}", ""), order_id) and order.get("user"):
        account = await customer_session(request)
        checkout_token_valid = bool(account and account["_id"] == order["user"])
    if not order or not (checkout_token_valid or order_access_token_valid(request.cookies.get(f"order_access_{order_id}", ""), order_id)):
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


async def order_tracking_view(order: dict[str, Any]) -> dict[str, Any]:
    payment = await db.payments.find_one({"order": order["_id"]}, {"provider": 1, "mode": 1, "status": 1, "currency": 1, "amount": 1, "verifiedAt": 1, "updatedAt": 1, "customerReportedAt": 1})
    history = order.get("statusHistory") or [{"status": "pending", "note": "Order placed", "at": order["createdAt"]}]
    return {
        "order": {
            "id": str(order["_id"]),
            "status": order["status"],
            "paymentStatus": order["paymentStatus"],
            "paymentProvider": order.get("paymentProvider"),
            "currency": order["currency"],
            "total": order["total"],
            "items": serialize([{key: item.get(key) for key in ("book", "title", "quantity", "unitPrice")} for item in order.get("items", [])]),
            "createdAt": serialize(order["createdAt"]),
            "customerName": decrypt_text(order.get("customer", {}).get("name", "")),
            "trackingNumber": order.get("trackingNumber", ""),
            "carrier": order.get("carrier", ""),
            "history": serialize([{key: entry.get(key) for key in ("status", "note", "at")} for entry in history]),
        },
        "payment": serialize(payment) if payment else None,
    }


@app.get("/api/payments/nepal/track/{order_id}")
async def track_payment(order_id: str, request: Request):
    return await order_tracking_view(await tracked_order(order_id, request))


@app.post("/api/orders/lookup")
async def lookup_order(payload: OrderLookupInput, request: Request, response: Response):
    require_frontend_origin(request)
    order = await db.orders.find_one({"_id": ObjectId(payload.orderId)})
    stored_email = normalized_email(decrypt_text(order.get("customer", {}).get("email", ""))) if order else ""
    # One generic error for unknown orders and wrong emails avoids revealing which order ids exist.
    if not order or not stored_email or not hmac.compare_digest(stored_email, normalized_email(str(payload.email))):
        raise HTTPException(status_code=404, detail="We could not find an order with that reference and email address.")
    set_order_access_cookie(response, payload.orderId)
    return await order_tracking_view(order)


@app.post("/api/payments/nepal/track/{order_id}/bank-reference")
async def submit_bank_reference(order_id: str, payload: BankReferenceInput, request: Request):
    require_frontend_origin(request)
    order = await tracked_order(order_id, request)
    if len(payload.reference) < 3:
        raise HTTPException(status_code=400, detail="Enter the transaction reference shown on your bank receipt.")
    if order.get("paymentProvider") != "bank_transfer" or order.get("paymentStatus") != "pending" or order.get("status") != "pending":
        raise HTTPException(status_code=409, detail="This order is not awaiting a bank transfer.")
    updated = await db.payments.find_one_and_update(
        {"order": order["_id"], "provider": "bank_transfer", "status": "pending"},
        {"$set": {
            "customerReference": encrypt_text(payload.reference),
            "customerNote": encrypt_text(payload.note),
            "customerReportedAt": now_utc(),
            "updatedAt": now_utc(),
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status_code=409, detail="This order is not awaiting a bank transfer.")
    await db.orders.update_one({"_id": order["_id"]}, {
        "$set": {"updatedAt": now_utc()},
        "$push": {"statusHistory": history_entry("pending", "Customer reported the bank transfer; awaiting verification.")},
    })
    await create_notification(
        "bank_reference",
        f"Bank transfer reported · NPR {order['total']:,.2f}",
        f"Reference {payload.reference} was submitted for order {order_id}. Check the bank statement, then confirm it in Payments.",
        order["_id"],
    )
    admin_email = normalized_email(os.getenv("ADMIN_EMAIL", ""))
    if admin_email:
        await send_store_email(
            admin_email,
            f"Bank transfer reported — {order_id}",
            f"The customer reported bank reference {payload.reference} for NPR {order['total']:.2f}.\nVerify it against the bank statement before confirming the payment.",
        )
    return await order_tracking_view(await db.orders.find_one({"_id": order["_id"]}) or order)


def admin_user_response(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(user["_id"]),
        "email": decrypt_text(user.get("email", "")),
        "role": user.get("role", ""),
        "permissions": ROLE_PERMISSIONS.get(user.get("role", ""), []),
    }


@app.get("/api/admin/auth/me")
async def admin_me(
    user: dict[str, Any] = Depends(require_admin),
):
    return {"user": admin_user_response(user)}


@app.get("/api/admin/analytics", dependencies=[Depends(require_permission("analytics:read"))])
async def analytics():
    books, gallery, team = await asyncio.gather(
        db.books.count_documents({"$or": [{"status": "published"}, {"status": {"$exists": False}}]}),
        db[MEDIA_COLLECTION].count_documents({"public": True, "category": "gallery"}),
        db.users.count_documents({"active": True, "role": {"$in": list(VALID_ROLES)}}),
    )
    return {"books": books, "gallery": gallery, "team": team}


async def aggregate_list(collection: Any, pipeline: list[dict[str, Any]], length: int | None) -> list[dict[str, Any]]:
    # AsyncCollection.aggregate is itself a coroutine that resolves to a cursor.
    cursor = await collection.aggregate(pipeline)
    return await cursor.to_list(length)


def local_today(timezone: str):
    try:
        return datetime.now(ZoneInfo(timezone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        # Windows hosts without tzdata fall back to Nepal's fixed UTC+05:45 offset.
        return (now_utc() + timedelta(hours=5, minutes=45)).date()


@app.get("/api/admin/store/analytics", dependencies=[Depends(require_permission("orders:read"))])
async def store_analytics():
    settings = await db[SETTINGS_COLLECTION].find_one({"_id": "store"}) or {}
    timezone = settings.get("timezone", "Asia/Kathmandu")
    # Paid orders that were later cancelled stay "paid" until refunded, but are not sales.
    confirmed = {"paymentStatus": "paid", "status": {"$ne": "cancelled"}}
    since = now_utc() - timedelta(days=60)
    # Every query below is independent, so they run concurrently instead of one round trip each.
    (
        revenue_summary, monthly_sales, daily_sales, by_method, top_books, statuses,
        order_count, pending_orders, to_fulfil, awaiting_bank, refunds_due, customer_count, low_stock,
    ) = await asyncio.gather(aggregate_list(db.orders, [
        {"$match": confirmed},
        {"$group": {"_id": None, "revenue": {"$sum": "$total"}, "paidOrders": {"$sum": 1}}},
    ], 1), aggregate_list(db.orders, [
        {"$match": {**confirmed, "createdAt": {"$type": "date"}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m", "date": "$createdAt", "timezone": timezone}},
            "revenue": {"$sum": "$total"},
            "orders": {"$sum": 1},
        }},
        {"$sort": {"_id": -1}},
        {"$limit": 12},
    ], 12), aggregate_list(db.orders, [
        {"$match": {**confirmed, "createdAt": {"$gte": since}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$createdAt", "timezone": timezone}},
            "revenue": {"$sum": "$total"},
            "orders": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ], 61), aggregate_list(db.orders, [
        {"$match": confirmed},
        {"$group": {"_id": "$paymentProvider", "revenue": {"$sum": "$total"}, "orders": {"$sum": 1}}},
        {"$sort": {"revenue": -1}},
    ], 10), aggregate_list(db.orders, [
        {"$match": confirmed},
        {"$unwind": "$items"},
        {"$group": {
            "_id": "$items.book",
            "title": {"$last": "$items.title"},
            "quantity": {"$sum": "$items.quantity"},
            "revenue": {"$sum": {"$multiply": ["$items.unitPrice", "$items.quantity"]}},
        }},
        {"$sort": {"quantity": -1, "revenue": -1}},
        {"$limit": 8},
    ], 8),
        aggregate_list(db.orders, [{"$group": {"_id": "$status", "count": {"$sum": 1}}}], 20),
        db.orders.count_documents({}),
        db.orders.count_documents({"status": "pending"}),
        db.orders.count_documents({"status": {"$in": ["paid", "processing"]}}),
        db.payments.count_documents({"provider": "bank_transfer", "status": "pending"}),
        db.orders.count_documents({"refundStatus": "due"}),
        db.customers.count_documents({}),
        db.books.count_documents({"$and": [
            {"$or": [{"stock": {"$lte": settings.get("lowStockThreshold", 5)}}, {"stock": {"$exists": False}}]},
            PUBLISHED_BOOK_QUERY,
        ]}),
    )
    revenue = revenue_summary[0] if revenue_summary else {}
    paid_orders = revenue.get("paidOrders", 0)
    revenue_total = round(float(revenue.get("revenue", 0)), 2)
    today = local_today(timezone)
    daily = {row["_id"]: row for row in daily_sales}
    last30 = [daily.get((today - timedelta(days=offset)).isoformat(), {}) for offset in range(29, -1, -1)]
    previous30 = [daily.get((today - timedelta(days=offset)).isoformat(), {}) for offset in range(59, 29, -1)]
    return {
        "orders": order_count,
        "paidOrders": paid_orders,
        "pendingOrders": pending_orders,
        "toFulfil": to_fulfil,
        "awaitingBankConfirmation": awaiting_bank,
        "refundsDue": refunds_due,
        "customers": customer_count,
        "revenueNpr": revenue_total,
        "averageOrderNpr": round(revenue_total / paid_orders, 2) if paid_orders else 0,
        "revenueLast30Npr": round(sum(float(row.get("revenue", 0)) for row in last30), 2),
        "revenuePrevious30Npr": round(sum(float(row.get("revenue", 0)) for row in previous30), 2),
        "lowStock": low_stock,
        "salesByMonth": [
            {"month": row["_id"], "revenueNpr": round(float(row.get("revenue", 0)), 2), "orders": row.get("orders", 0)}
            for row in reversed(monthly_sales)
        ],
        "salesByDay": [
            {"day": (today - timedelta(days=29 - index)).isoformat(), "revenueNpr": round(float(row.get("revenue", 0)), 2), "orders": row.get("orders", 0)}
            for index, row in enumerate(last30)
        ],
        "salesByMethod": [
            {"method": row["_id"] or "unknown", "revenueNpr": round(float(row.get("revenue", 0)), 2), "orders": row.get("orders", 0)}
            for row in by_method
        ],
        "topBooks": [
            {"bookId": str(row["_id"]), "title": row.get("title", "Book"), "quantity": row.get("quantity", 0), "revenueNpr": round(float(row.get("revenue", 0)), 2)}
            for row in top_books
        ],
        "statusCounts": {row["_id"] or "unknown": row["count"] for row in statuses},
    }


@app.get("/api/admin/users")
async def list_users(_: dict[str, Any] = Depends(require_permission("users:manage"))):
    users = await db.users.find({"role": {"$in": list(VALID_ROLES)}}, {"email": 1, "role": 1, "active": 1, "createdAt": 1}).sort("createdAt", -1).to_list(500)
    return {"users": [serialize(item) for item in users]}


@app.post("/api/admin/users", status_code=201)
async def create_user(payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("users:manage"))):
    if set(payload) - {"email", "password", "role", "active"}:
        raise HTTPException(status_code=400, detail="Only email, password, role, and active are accepted.")
    email = normalized_email(str(payload.get("email", "")))
    password = payload.get("password")
    role = payload.get("role")
    active = payload.get("active", True)
    if not EMAIL_PATTERN.fullmatch(email) or not isinstance(password, str) or len(password) < 12 or role not in VALID_ROLES or not isinstance(active, bool):
        raise HTTPException(status_code=400, detail="Provide a valid email, a password of at least 12 characters, and a valid role.")
    stamp = now_utc()
    created = {
        "email": encrypt_text(email), "emailHash": email_index(email),
        "passwordHash": PASSWORD_HASHER.hash(password), "role": role,
        "active": active, "emailVerified": True,
        "authVersion": 0,
        "createdAt": stamp, "updatedAt": stamp,
    }
    result = await db.users.insert_one(created)
    created["_id"] = result.inserted_id
    await audit(user, "create", "user", str(result.inserted_id), {"role": role}, request_ip(request))
    return {"user": serialize(created)}


@app.patch("/api/admin/users/{user_id}")
async def update_user(user_id: str, payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("users:manage"))):
    oid = require_object_id(user_id, "user")
    allowed = {"role", "active", "password"}
    if not payload or set(payload) - allowed:
        raise HTTPException(status_code=400, detail="Only role, active, and password are editable.")
    target = await db.users.find_one({"_id": oid})
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    role = payload.get("role", target.get("role"))
    active = payload.get("active", target.get("active", True))
    if role not in VALID_ROLES or not isinstance(active, bool):
        raise HTTPException(status_code=400, detail="Invalid user role or active flag.")
    changing_last_admin = target.get("role") == "admin" and target.get("active", True) and (role != "admin" or not active)
    if changing_last_admin and await db.users.count_documents({"role": "admin", "active": True}) <= 1:
        raise HTTPException(status_code=409, detail="At least one active administrator must remain.")
    if oid == user["_id"] and not active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    updates: dict[str, Any] = {"role": role, "active": active, "updatedAt": now_utc()}
    if "password" in payload:
        password = payload["password"]
        if not isinstance(password, str) or len(password) < 12:
            raise HTTPException(status_code=400, detail="Password must be at least 12 characters.")
        updates["passwordHash"] = PASSWORD_HASHER.hash(password)
        updates["authVersion"] = target.get("authVersion", 0) + 1
    await db.users.update_one({"_id": oid}, {"$set": updates})
    updated = await db.users.find_one({"_id": oid})
    await audit(user, "update", "user", user_id, {"fields": sorted(payload)}, request_ip(request))
    return {"user": serialize(updated)}


@app.delete("/api/admin/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request, response: Response, user: dict[str, Any] = Depends(require_permission("users:manage"))):
    oid = require_object_id(user_id, "user")
    if oid == user["_id"]:
        raise HTTPException(status_code=400, detail="You cannot remove your own account.")
    target = await db.users.find_one({"_id": oid})
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.get("role") == "admin" and target.get("active", True) and await db.users.count_documents({"role": "admin", "active": True}) <= 1:
        raise HTTPException(status_code=409, detail="At least one active administrator must remain.")
    await db.users.delete_one({"_id": oid})
    await db.auth_sessions.delete_many({"user": oid})
    await audit(user, "delete", "user", user_id, ip=request_ip(request))
    response.status_code = 204
    return response


def validate_resource_fields(payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload or set(payload) - allowed:
        raise HTTPException(status_code=400, detail="A JSON object with editable fields is required.")
    if any(key.startswith("$") or "." in key for key in payload):
        raise HTTPException(status_code=400, detail="Invalid field name.")
    return payload


async def admin_list(collection_name: str, key: str):
    rows = await db[collection_name].find().sort("createdAt", -1).limit(500).to_list(500)
    return {key: [serialize(item) for item in rows]}


async def create_resource(collection_name: str, key: str, payload: dict[str, Any], allowed: set[str], resource: str, user: dict[str, Any], request: Request):
    fields = validate_resource_fields(payload, allowed)
    required = {
        "books": {"title", "description", "image"},
        "customers": {"name", "email"},
        "reviews": {"book", "customerName", "rating", "body"},
        MEDIA_COLLECTION: {"title", "url"},
    }.get(collection_name, set())
    if required - fields.keys():
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(sorted(required - fields.keys()))}.")
    if collection_name == MEDIA_COLLECTION:
        validate_media(fields)
    data = encrypt_fields(fields)
    stamp = now_utc()
    data.update({"createdAt": stamp, "updatedAt": stamp})
    if collection_name == "books":
        validate_book(fields)
    elif collection_name == "customers":
        data["emailHash"] = email_index(normalized_email(str(fields.get("email", ""))))
    elif collection_name == "reviews":
        data["book"] = require_object_id(str(fields.get("book", "")), "book")
        validate_review(fields)
        if not await db.books.find_one({"_id": data["book"]}, {"_id": 1}):
            raise HTTPException(status_code=400, detail="Review book was not found.")
    result = await db[collection_name].insert_one(data)
    data["_id"] = result.inserted_id
    await audit(user, "create", resource, str(result.inserted_id), ip=request_ip(request))
    return {key: serialize(data)}


def validate_book(fields: dict[str, Any]) -> None:
    if "title" in fields and (not isinstance(fields["title"], str) or not fields["title"].strip() or len(fields["title"]) > 160):
        raise HTTPException(status_code=400, detail="Book title is required and must be at most 160 characters.")
    if "format" in fields and (not isinstance(fields["format"], str) or len(fields["format"]) > 80):
        raise HTTPException(status_code=400, detail="Work type must be at most 80 characters.")
    if "status" in fields and fields["status"] not in {"draft", "published"}:
        raise HTTPException(status_code=400, detail="Publication status must be draft or published.")
    if "image" in fields:
        validate_media({"url": fields["image"]})
    if "year" in fields and fields["year"] is not None and (isinstance(fields["year"], bool) or not isinstance(fields["year"], int) or not 0 <= fields["year"] <= 9999):
        raise HTTPException(status_code=400, detail="Publication year is invalid.")
    if "category" in fields and (not isinstance(fields["category"], str) or not fields["category"].strip() or len(fields["category"]) > 80):
        raise HTTPException(status_code=400, detail="Book category is required and must be at most 80 characters.")
    if "priceNpr" in fields:
        price = fields["priceNpr"]
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not 0 < price <= 10_000_000 or not math.isfinite(price):
            raise HTTPException(status_code=400, detail="Book price must be greater than zero and at most NPR 10,000,000.")
    if "stock" in fields and (isinstance(fields["stock"], bool) or not isinstance(fields["stock"], int) or not 0 <= fields["stock"] <= 1_000_000):
        raise HTTPException(status_code=400, detail="Book inventory must be a whole number between zero and 1,000,000.")


def validate_public_content(key: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="Published website content must be a JSON object.")
    allowed = {
        "author-profile": {
            "name", "role", "email", "location", "portrait", "landscape", "heroLead",
            "heroEmphasis", "heroDescription", "aboutHeading", "aboutBiography",
            "aboutPageTitle", "aboutPageBiography", "quote", "instagram", "facebook", "linkedin",
            "tiktok", "youtube", "threads",
        },
        "site-settings": {"siteTitle", "seoTitle", "seoDescription", "ogImage"},
    }[key]
    if set(value) - allowed:
        raise HTTPException(status_code=400, detail="Website content contains unsupported fields.")
    for field, item in value.items():
        limit = 320 if field == "seoDescription" else 120 if field in {"siteTitle", "seoTitle"} else 2048 if field.endswith(("Image", "portrait", "landscape")) or field in {"instagram", "facebook", "linkedin", "tiktok", "youtube", "threads"} else 5000
        if not isinstance(item, str) or len(item) > limit:
            raise HTTPException(status_code=400, detail=f"{field} must be text no longer than {limit} characters.")
        if field == "email" and item and not EMAIL_PATTERN.fullmatch(item):
            raise HTTPException(status_code=400, detail="Provide a valid public contact email address.")
        if field in {"portrait", "landscape"} and item:
            if not (item.startswith("https://") or (item.startswith("/") and not item.startswith("//"))):
                raise HTTPException(status_code=400, detail=f"{field} must use HTTPS or a local site path.")
        elif field == "ogImage" and item:
            validate_media({"url": item})
        elif field in {"instagram", "facebook", "linkedin", "tiktok", "youtube", "threads"} and item:
            validate_media({"url": item})


def validate_review(fields: dict[str, Any]) -> None:
    rating = fields.get("rating")
    if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5):
        raise HTTPException(status_code=400, detail="Review rating must be an integer from one to five.")
    if "status" in fields and fields["status"] not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid review status.")


async def update_resource(collection_name: str, key: str, raw_id: str, payload: dict[str, Any], allowed: set[str], resource: str, user: dict[str, Any], request: Request):
    fields = validate_resource_fields(payload, allowed)
    query: dict[str, Any]
    if collection_name == CONTENT_COLLECTION:
        query = {"key": raw_id}
    else:
        query = {"_id": require_object_id(raw_id, resource)}
    if collection_name == MEDIA_COLLECTION:
        validate_media(fields)
    data = encrypt_fields(fields)
    if collection_name == "books":
        validate_book(fields)
    elif collection_name == "customers" and "email" in fields:
        data["emailHash"] = email_index(normalized_email(str(fields["email"])))
    elif collection_name == "reviews" and "book" in fields:
        data["book"] = require_object_id(str(fields["book"]), "book")
        if not await db.books.find_one({"_id": data["book"]}, {"_id": 1}):
            raise HTTPException(status_code=400, detail="Review book was not found.")
    if collection_name == "reviews":
        validate_review(fields)
    if collection_name == CONTENT_COLLECTION:
        data.update({"updatedAt": now_utc(), "updatedBy": user["_id"]})
        updated = await db[collection_name].find_one_and_update(query, {"$set": data, "$setOnInsert": {"createdAt": now_utc()}}, upsert=True, return_document=ReturnDocument.AFTER)
        action = "upsert"
    else:
        data["updatedAt"] = now_utc()
        updated = await db[collection_name].find_one_and_update(query, {"$set": data}, return_document=ReturnDocument.AFTER)
        if not updated:
            raise HTTPException(status_code=404, detail=f"{resource.title()} not found.")
        action = "update"
    await audit(user, action, resource, raw_id, {"fields": sorted(fields)}, request_ip(request))
    return {key: serialize(updated)}


def validate_media(fields: dict[str, Any]) -> None:
    if "title" in fields and (not isinstance(fields["title"], str) or not fields["title"].strip() or len(fields["title"]) > 160):
        raise HTTPException(status_code=400, detail="Media title is required and must be at most 160 characters.")
    if "url" in fields:
        value = fields["url"]
        try:
            parsed = urlparse(value) if isinstance(value, str) else None
            hostname = parsed.hostname if parsed else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Media URLs must use a valid HTTPS address.") from exc
        if (
            not isinstance(value, str)
            or len(value) > 2048
            or not parsed
            or parsed.scheme != "https"
            or not hostname
            or "*" in hostname
            or parsed.username
            or parsed.password
        ):
            raise HTTPException(status_code=400, detail="Media URLs must use a valid HTTPS address.")
    if "altText" in fields and (not isinstance(fields["altText"], str) or len(fields["altText"]) > 500):
        raise HTTPException(status_code=400, detail="Alternative text must be at most 500 characters.")
    if "category" in fields and fields["category"] not in {"author", "book-cover", "site", "gallery", "other"}:
        raise HTTPException(status_code=400, detail="Invalid media category.")
    if "public" in fields and not isinstance(fields["public"], bool):
        raise HTTPException(status_code=400, detail="Gallery visibility must be a boolean.")
    if "notes" in fields and (not isinstance(fields["notes"], str) or len(fields["notes"]) > 2000):
        raise HTTPException(status_code=400, detail="Media notes must be at most 2,000 characters.")


async def delete_resource(collection_name: str, raw_id: str, resource: str, user: dict[str, Any], request: Request, *, content: bool = False):
    query = {"key": raw_id} if content else {"_id": require_object_id(raw_id, resource)}
    deleted = await db[collection_name].find_one_and_delete(query)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"{resource.title()} not found.")
    await audit(user, "delete", resource, raw_id, ip=request_ip(request))
    return Response(status_code=204)


@app.get("/api/admin/books", dependencies=[Depends(require_permission("books:read"))])
async def admin_books():
    projection = {
        "title": 1, "subtitle": 1, "description": 1, "image": 1, "format": 1,
        "year": 1, "status": 1, "category": 1, "priceNpr": 1, "stock": 1,
        "createdAt": 1, "updatedAt": 1,
    }
    rows = await db.books.find({}, projection).sort("createdAt", -1).limit(500).to_list(500)
    return {"books": [serialize(row) for row in rows]}


@app.post("/api/admin/books", status_code=201)
async def admin_create_book(payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("books:write"))):
    return await create_resource("books", "book", payload, BOOK_FIELDS, "book", user, request)


@app.patch("/api/admin/books/{item_id}")
async def admin_update_book(item_id: str, payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("books:write"))):
    return await update_resource("books", "book", item_id, payload, BOOK_FIELDS, "book", user, request)


@app.delete("/api/admin/books/{item_id}", status_code=204)
async def admin_delete_book(item_id: str, request: Request, user: dict[str, Any] = Depends(require_permission("books:write"))):
    return await delete_resource("books", item_id, "book", user, request)


@app.post("/api/admin/books/{item_id}/stock")
async def admin_adjust_stock(item_id: str, payload: StockAdjustmentInput, request: Request, user: dict[str, Any] = Depends(require_permission("books:write"))):
    oid = require_object_id(item_id, "book")
    # A conditional $inc keeps concurrent checkouts and adjustments from driving stock below zero.
    query: dict[str, Any] = {"_id": oid}
    if payload.delta < 0:
        query["stock"] = {"$gte": -payload.delta}
    else:
        query["$or"] = [{"stock": {"$exists": False}}, {"stock": {"$lte": 1_000_000 - payload.delta}}]
    updated = await db.books.find_one_and_update(
        query,
        {"$inc": {"stock": payload.delta}, "$set": {"updatedAt": now_utc()}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        if not await db.books.find_one({"_id": oid}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Book not found.")
        raise HTTPException(status_code=409, detail="Stock cannot go below zero or above 1,000,000.")
    await audit(user, "adjust-stock", "book", item_id, {"delta": payload.delta, "reason": payload.reason.strip(), "stock": updated.get("stock")}, request_ip(request))
    return {"book": serialize(updated)}


@app.get("/api/admin/customers", dependencies=[Depends(require_permission("customers:read"))])
async def admin_customers():
    result = await admin_list("customers", "customers")
    stats = await aggregate_list(db.orders, [
        {"$match": {"customerRecord": {"$exists": True}}},
        {"$group": {
            "_id": "$customerRecord",
            "orderCount": {"$sum": 1},
            "totalSpent": {"$sum": {"$cond": [{"$and": [{"$eq": ["$paymentStatus", "paid"]}, {"$ne": ["$status", "cancelled"]}]}, "$total", 0]}},
            "lastOrderAt": {"$max": "$createdAt"},
        }},
    ], None)
    by_customer = {str(row["_id"]): row for row in stats}
    for customer in result["customers"]:
        row = by_customer.get(customer["_id"], {})
        customer["orderCount"] = row.get("orderCount", 0)
        customer["totalSpent"] = round(float(row.get("totalSpent", 0)), 2)
        customer["lastOrderAt"] = serialize(row.get("lastOrderAt"))
    return result


@app.get("/api/admin/customers/{item_id}/orders", dependencies=[Depends(require_permission("customers:read"))])
async def admin_customer_orders(item_id: str):
    oid = require_object_id(item_id, "customer")
    orders = await db.orders.find({"customerRecord": oid}).sort("createdAt", -1).limit(200).to_list(200)
    return {"orders": [admin_order_view(order) for order in orders]}


@app.post("/api/admin/customers", status_code=201)
async def admin_create_customer(payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("customers:write"))):
    return await create_resource("customers", "customer", payload, CUSTOMER_FIELDS, "customer", user, request)


@app.patch("/api/admin/customers/{item_id}")
async def admin_update_customer(item_id: str, payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("customers:write"))):
    return await update_resource("customers", "customer", item_id, payload, CUSTOMER_FIELDS, "customer", user, request)


@app.delete("/api/admin/customers/{item_id}", status_code=204)
async def admin_delete_customer(item_id: str, request: Request, user: dict[str, Any] = Depends(require_permission("customers:write"))):
    return await delete_resource("customers", item_id, "customer", user, request)


async def admin_reviews():
    rows = await db.reviews.find().sort("createdAt", -1).limit(500).to_list(500)
    for row in rows:
        book = await db.books.find_one({"_id": row.get("book")}, {"title": 1})
        if book:
            row["book"] = {"_id": str(book["_id"]), "title": book["title"]}
    return {"reviews": [serialize(row) for row in rows]}


async def admin_create_review(payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("reviews:write"))):
    return await create_resource("reviews", "review", payload, REVIEW_FIELDS, "review", user, request)


async def admin_update_review(item_id: str, payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("reviews:write"))):
    return await update_resource("reviews", "review", item_id, payload, REVIEW_FIELDS - {"book"}, "review", user, request)


async def admin_delete_review(item_id: str, request: Request, user: dict[str, Any] = Depends(require_permission("reviews:write"))):
    return await delete_resource("reviews", item_id, "review", user, request)


@app.get("/api/admin/media", dependencies=[Depends(require_permission("media:read"))])
async def admin_media():
    return await admin_list(MEDIA_COLLECTION, "media")


@app.post("/api/admin/media", status_code=201)
async def admin_create_media(payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("media:write"))):
    return await create_resource(MEDIA_COLLECTION, "media", payload, MEDIA_FIELDS, "media", user, request)


@app.patch("/api/admin/media/{item_id}")
async def admin_update_media(item_id: str, payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("media:write"))):
    return await update_resource(MEDIA_COLLECTION, "media", item_id, payload, MEDIA_FIELDS, "media", user, request)


@app.delete("/api/admin/media/{item_id}", status_code=204)
async def admin_delete_media(item_id: str, request: Request, user: dict[str, Any] = Depends(require_permission("media:write"))):
    return await delete_resource(MEDIA_COLLECTION, item_id, "media", user, request)


@app.get("/api/admin/content", dependencies=[Depends(require_permission("content:read"))])
async def admin_content():
    rows = await db[CONTENT_COLLECTION].find().sort("key", 1).to_list(500)
    return {"content": [serialize(item) for item in rows]}


@app.put("/api/admin/content/{key}")
async def admin_upsert_content(key: str, payload: dict[str, Any], request: Request, user: dict[str, Any] = Depends(require_permission("content:write"))):
    if not re.fullmatch(r"[a-z0-9-]{1,80}", key):
        raise HTTPException(status_code=400, detail="Invalid content key.")
    if "value" not in payload or set(payload) - {"value", "public"} or ("public" in payload and not isinstance(payload["public"], bool)):
        raise HTTPException(status_code=400, detail="A content value and optional boolean public flag are required.")
    if key in {"author-profile", "site-settings"}:
        validate_public_content(key, payload["value"])
    return await update_resource(CONTENT_COLLECTION, "content", key, payload, {"value", "public"}, "content", user, request)


@app.delete("/api/admin/content/{key}", status_code=204)
async def admin_delete_content(key: str, request: Request, user: dict[str, Any] = Depends(require_permission("content:write"))):
    return await delete_resource(CONTENT_COLLECTION, key, "content", user, request, content=True)


@app.get("/api/admin/settings", dependencies=[Depends(require_permission("settings:read"))])
async def admin_settings():
    settings = await db[SETTINGS_COLLECTION].find_one({"_id": "store"})
    return {
        "settings": {
            "storeName": settings.get("storeName", "Author Bookstore") if settings else "Author Bookstore",
            "contactEmail": decrypt_text(settings.get("contactEmail", "")) if settings else "",
            "defaultCurrency": settings.get("defaultCurrency", "npr") if settings else "npr",
            "lowStockThreshold": settings.get("lowStockThreshold", 5) if settings else 5,
            "timezone": settings.get("timezone", "Asia/Kathmandu") if settings else "Asia/Kathmandu",
            "bankName": settings.get("bankName", "") if settings else "",
            "bankAccountName": settings.get("bankAccountName", "") if settings else "",
            "bankAccountNumber": decrypt_text(settings.get("bankAccountNumber", "")) if settings else "",
            "bankBranch": settings.get("bankBranch", "") if settings else "",
            "bankInstructions": settings.get("bankInstructions", "") if settings else "",
            "updatedAt": serialize(settings.get("updatedAt")) if settings and settings.get("updatedAt") else None,
        }
    }


@app.put("/api/admin/settings")
async def update_admin_settings(payload: AdminSettingsInput, request: Request, user: dict[str, Any] = Depends(require_permission("settings:write"))):
    raw_updates = payload.model_dump(exclude_unset=True)
    if not raw_updates:
        raise HTTPException(status_code=400, detail="Provide at least one setting to update.")
    if "contactEmail" in raw_updates and raw_updates["contactEmail"] and not EMAIL_PATTERN.fullmatch(raw_updates["contactEmail"]):
        raise HTTPException(status_code=400, detail="Provide a valid contact email address.")
    updates = encrypt_fields(raw_updates)
    updates.update({"updatedAt": now_utc(), "updatedBy": user["_id"]})
    settings = await db[SETTINGS_COLLECTION].find_one_and_update(
        {"_id": "store"},
        {"$set": updates, "$setOnInsert": {"createdAt": now_utc()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    await audit(user, "update", "settings", "store", {"fields": sorted(raw_updates)}, request_ip(request))
    return {"settings": serialize(settings)}


def admin_order_view(order: dict[str, Any]) -> dict[str, Any]:
    view = serialize(order)
    view["paymentReference"] = decrypt_text(order.get("paymentReference", ""))
    view["refundReference"] = decrypt_text(order.get("refundReference", ""))
    if not order.get("statusHistory"):
        view["statusHistory"] = serialize([{"status": "pending", "note": "Order placed", "at": order.get("createdAt")}])
    return view


@app.get("/api/admin/orders", dependencies=[Depends(require_permission("orders:read"))])
async def admin_orders():
    orders = await db.orders.find().sort("createdAt", -1).limit(500).to_list(500)
    customer_ids = list({order["customerRecord"] for order in orders if isinstance(order.get("customerRecord"), ObjectId)})
    customers = {
        row["_id"]: serialize(row)
        for row in await db.customers.find({"_id": {"$in": customer_ids}}, {"name": 1, "email": 1, "phone": 1}).to_list(len(customer_ids) or 1)
    }
    views = []
    for order in orders:
        view = admin_order_view(order)
        if order.get("customerRecord") in customers:
            view["customerRecord"] = customers[order["customerRecord"]]
        views.append(view)
    return {"orders": views}


def csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # Prevent spreadsheet formula injection from customer-entered text.
    return f"'{text}" if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text


@app.get("/api/admin/orders/export")
async def export_orders(request: Request, user: dict[str, Any] = Depends(require_permission("orders:read"))):
    orders = await db.orders.find().sort("createdAt", -1).limit(5000).to_list(5000)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Order", "Created (UTC)", "Customer", "Email", "Phone", "Address", "Items", "Total (NPR)", "Payment method", "Payment status", "Order status", "Payment reference", "Carrier", "Tracking number"])
    for order in orders:
        customer = order.get("customer", {})
        writer.writerow([csv_cell(value) for value in (
            order["_id"],
            order["createdAt"].isoformat() if isinstance(order.get("createdAt"), datetime) else "",
            decrypt_text(customer.get("name", "")),
            decrypt_text(customer.get("email", "")),
            decrypt_text(customer.get("phone", "")),
            decrypt_text(customer.get("address", "")),
            "; ".join(f'{item.get("title", "Book")} x {item.get("quantity", 0)}' for item in order.get("items", [])),
            f'{float(order.get("total", 0)):.2f}',
            order.get("paymentProvider", ""),
            order.get("paymentStatus", ""),
            order.get("status", ""),
            decrypt_text(order.get("paymentReference", "")),
            order.get("carrier", ""),
            order.get("trackingNumber", ""),
        )])
    await audit(user, "export", "order", "", {"count": len(orders)}, request_ip(request))
    filename = f"orders-{now_utc():%Y%m%d}.csv"
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.patch("/api/admin/orders/{order_id}")
async def update_order_status(order_id: str, payload: OrderStatusInput, request: Request, user: dict[str, Any] = Depends(require_permission("orders:write"))):
    oid = require_object_id(order_id, "order")
    order = await db.orders.find_one({"_id": oid})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    current = order["status"]
    if payload.status not in ORDER_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=409, detail="That order status transition is not allowed.")
    if payload.status == "cancelled" and current == "pending":
        await release_inventory(order, payload.note or "Cancelled by the bookstore.")
        if (await db.orders.find_one({"_id": oid}, {"status": 1}) or {}).get("status") != "cancelled":
            raise HTTPException(status_code=409, detail="The order has already changed.")
    elif payload.status == "cancelled":
        # A paid order is cancelled, restocked, and flagged for a refund the admin records separately.
        cancelled = await db.orders.find_one_and_update(
            {"_id": oid, "status": current, "paymentStatus": "paid"},
            {
                "$set": {"status": "cancelled", "refundStatus": "due", "stockDeducted": False, "updatedAt": now_utc()},
                "$push": {"statusHistory": history_entry("cancelled", payload.note or "Cancelled by the bookstore. A refund is being arranged.", by=user["_id"])},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not cancelled:
            raise HTTPException(status_code=409, detail="The order has already changed.")
        if order.get("stockDeducted", True):
            for item in cancelled.get("items", []):
                await db.books.update_one({"_id": item["book"]}, {"$inc": {"stock": item["quantity"]}})
    else:
        updates: dict[str, Any] = {"status": payload.status, "updatedAt": now_utc()}
        if payload.status == "shipped":
            updates.update({"trackingNumber": payload.trackingNumber, "carrier": payload.carrier, "shippedAt": now_utc()})
        if payload.status == "fulfilled":
            updates["deliveredAt"] = now_utc()
        changed = await db.orders.update_one(
            {"_id": oid, "status": current},
            {"$set": updates, "$push": {"statusHistory": history_entry(payload.status, payload.note, by=user["_id"])}},
        )
        if changed.modified_count != 1:
            raise HTTPException(status_code=409, detail="The order has already changed.")
    await audit(user, "update", "order", order_id, {"status": payload.status, "from": current}, request_ip(request))
    updated = await db.orders.find_one({"_id": oid})
    if updated:
        await notify_order_status(updated, payload.note)
    return {"order": admin_order_view(updated)}


@app.post("/api/admin/orders/{order_id}/refund")
async def record_refund(order_id: str, payload: OrderRefundInput, request: Request, user: dict[str, Any] = Depends(require_permission("payments:reconcile"))):
    oid = require_object_id(order_id, "order")
    refunded = await db.orders.find_one_and_update(
        {"_id": oid, "status": "cancelled", "refundStatus": "due"},
        {
            "$set": {"paymentStatus": "refunded", "refundStatus": "refunded", "refundReference": encrypt_text(payload.reference), "refundedAt": now_utc(), "updatedAt": now_utc()},
            "$push": {"statusHistory": history_entry("cancelled", "Refund issued.", by=user["_id"])},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not refunded:
        raise HTTPException(status_code=409, detail="This order is not awaiting a refund.")
    await db.payments.update_many({"order": oid, "status": "completed"}, {"$set": {"status": "refunded", "updatedAt": now_utc()}})
    await audit(user, "refund", "order", order_id, {"provider": refunded.get("paymentProvider")}, request_ip(request))
    await notify_order_status(refunded, "Your refund has been issued.")
    return {"order": admin_order_view(refunded)}


@app.get("/api/admin/payments", dependencies=[Depends(require_permission("payments:read"))])
async def admin_payments():
    payments = await db.payments.find().sort("createdAt", -1).limit(500).to_list(500)
    order_ids = list({payment["order"] for payment in payments if isinstance(payment.get("order"), ObjectId)})
    orders = {
        row["_id"]: row
        for row in await db.orders.find(
            {"_id": {"$in": order_ids}},
            {"customer": 1, "total": 1, "currency": 1, "status": 1, "paymentStatus": 1, "createdAt": 1},
        ).to_list(len(order_ids) or 1)
    }
    for payment in payments:
        if payment.get("order") in orders:
            payment["order"] = orders[payment["order"]]
    views = []
    for payment in payments:
        view = serialize(payment)
        # Admins need the plain references to reconcile against provider and bank statements.
        for key in ("providerTransactionId", "customerReference", "customerNote"):
            view[key] = decrypt_text(payment.get(key, ""))
        view.pop("providerReference", None)
        views.append(view)
    return {"payments": views}


@app.post("/api/admin/payments/{payment_id}/reconcile")
async def reconcile_payment(payment_id: str, request: Request, user: dict[str, Any] = Depends(require_permission("payments:reconcile"))):
    oid = require_object_id(payment_id, "payment")
    payment = await db.payments.find_one({"_id": oid})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")
    order = await db.orders.find_one({"_id": payment["order"]})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if payment["provider"] == "khalti":
        result = await verify_khalti_payment(payment, order)
    elif payment["provider"] == "esewa":
        result = await verify_esewa_payment(payment, order)
    else:
        raise HTTPException(status_code=503, detail=f'{payment["provider"]} is not configured for payment reconciliation.')
    await audit(user, "reconcile", "payment", payment_id, {"status": result["status"]}, request_ip(request))
    return {"payment": serialize(result)}


@app.post("/api/admin/payments/{payment_id}/confirm")
async def confirm_bank_payment(
    payment_id: str,
    payload: BankPaymentConfirmationInput,
    request: Request,
    user: dict[str, Any] = Depends(require_permission("payments:reconcile")),
):
    oid = require_object_id(payment_id, "payment")
    payment = await db.payments.find_one({"_id": oid, "provider": "bank_transfer", "status": "pending"})
    if not payment:
        raise HTTPException(status_code=404, detail="A pending bank-transfer payment was not found.")
    order = await db.orders.find_one({
        "_id": payment["order"],
        "paymentProvider": "bank_transfer",
        "paymentStatus": "pending",
        "status": "pending",
        "stockDeducted": True,
    })
    if not order:
        raise HTTPException(status_code=409, detail="The order is no longer awaiting bank-transfer confirmation.")
    confirmed_at = now_utc()
    confirmed_order = await db.orders.find_one_and_update(
        {"_id": order["_id"], "status": "pending", "paymentStatus": "pending"},
        {
            "$set": {"status": "paid", "paymentStatus": "paid", "paymentReference": encrypt_text(payload.transactionReference or str(order["_id"])), "updatedAt": confirmed_at},
            "$push": {"statusHistory": history_entry("paid", "Bank transfer verified by the bookstore.", by=user["_id"])},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not confirmed_order:
        raise HTTPException(status_code=409, detail="The order has already changed.")
    await db.payments.update_one(
        {"_id": oid, "status": "pending"},
        {"$set": {
            "status": "completed",
            "providerTransactionId": encrypt_text(payload.transactionReference),
            "verifiedAt": confirmed_at,
            "lastCheckedAt": confirmed_at,
            "updatedAt": confirmed_at,
        }},
    )
    await audit(user, "confirm", "payment", payment_id, {"provider": "bank_transfer", "order": str(order["_id"])}, request_ip(request))
    await notify_payment_confirmed(confirmed_order)
    return {"order": serialize(confirmed_order), "payment": serialize(await db.payments.find_one({"_id": oid}))}


@app.get("/api/admin/accounts", dependencies=[Depends(require_permission("customers:read"))])
async def admin_accounts():
    rows = await db.users.find({"role": "customer"}).sort("createdAt", -1).limit(1000).to_list(1000)
    counts = {
        row["_id"]: row
        for row in await aggregate_list(db.orders, [
            {"$match": {"user": {"$in": [row["_id"] for row in rows]}}},
            {"$group": {"_id": "$user", "orders": {"$sum": 1}, "lastOrderAt": {"$max": "$createdAt"}}},
        ], None)
    }
    return {"accounts": [{
        **customer_view(row),
        "active": row.get("active", True),
        "orderCount": counts.get(row["_id"], {}).get("orders", 0),
        "lastOrderAt": serialize(counts.get(row["_id"], {}).get("lastOrderAt")),
    } for row in rows]}


@app.patch("/api/admin/accounts/{account_id}")
async def admin_update_account(account_id: str, payload: AccountStatusInput, request: Request, user: dict[str, Any] = Depends(require_permission("customers:write"))):
    oid = require_object_id(account_id, "account")
    updated = await db.users.find_one_and_update(
        {"_id": oid, "role": "customer"},
        {"$set": {"active": payload.active, "updatedAt": now_utc()}, "$inc": {"authVersion": 0 if payload.active else 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Customer account not found.")
    if not payload.active:
        await db.auth_sessions.delete_many({"user": oid})
    await audit(user, "activate" if payload.active else "deactivate", "account", account_id, ip=request_ip(request))
    return {"account": {**customer_view(updated), "active": updated.get("active", True)}}


@app.get("/api/admin/notifications", dependencies=[Depends(require_permission("orders:read"))])
async def admin_notifications():
    rows = await db[NOTIFICATION_COLLECTION].find().sort("createdAt", -1).limit(50).to_list(50)
    return {
        "notifications": [serialize(row) for row in rows],
        "unread": await db[NOTIFICATION_COLLECTION].count_documents({"read": False}),
    }


@app.post("/api/admin/notifications/read")
async def mark_notifications_read(payload: NotificationReadInput, _: dict[str, Any] = Depends(require_permission("orders:read"))):
    query: dict[str, Any] = {"read": False}
    if payload.ids:
        query["_id"] = {"$in": [require_object_id(raw_id, "notification") for raw_id in payload.ids]}
    result = await db[NOTIFICATION_COLLECTION].update_many(query, {"$set": {"read": True, "readAt": now_utc()}})
    return {"updated": result.modified_count}


@app.get("/api/admin/categories", dependencies=[Depends(require_permission("books:read"))])
async def admin_categories():
    rows = await db[CATEGORY_COLLECTION].find().sort([("sortOrder", 1), ("name", 1)]).to_list(200)
    counts = {
        row["_id"]: row["count"]
        for row in await aggregate_list(db.books, [{"$group": {"_id": "$category", "count": {"$sum": 1}}}], None)
    }
    managed = {row.get("name") for row in rows}
    categories = [serialize({**row, "bookCount": counts.get(row.get("name"), 0)}) for row in rows]
    # Categories typed directly on books before category management existed.
    unmanaged = sorted(name for name in counts if isinstance(name, str) and name and name not in managed)
    return {"categories": categories, "unmanaged": [{"name": name, "bookCount": counts[name]} for name in unmanaged]}


@app.post("/api/admin/categories", status_code=201)
async def admin_create_category(payload: CategoryInput, request: Request, user: dict[str, Any] = Depends(require_permission("books:write"))):
    if not payload.name or not category_slug(payload.name):
        raise HTTPException(status_code=400, detail="Category name is required.")
    stamp = now_utc()
    created = {
        "name": payload.name,
        "slug": category_slug(payload.name),
        "description": payload.description or "",
        "sortOrder": payload.sortOrder if payload.sortOrder is not None else 100,
        "active": payload.active if payload.active is not None else True,
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    try:
        result = await db[CATEGORY_COLLECTION].insert_one(created)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="A category with that name already exists.") from exc
    created["_id"] = result.inserted_id
    await audit(user, "create", "category", str(result.inserted_id), ip=request_ip(request))
    return {"category": serialize(created)}


@app.patch("/api/admin/categories/{category_id}")
async def admin_update_category(category_id: str, payload: CategoryInput, request: Request, user: dict[str, Any] = Depends(require_permission("books:write"))):
    oid = require_object_id(category_id, "category")
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Provide at least one category field to update.")
    existing = await db[CATEGORY_COLLECTION].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found.")
    if "name" in updates:
        if not category_slug(updates["name"]):
            raise HTTPException(status_code=400, detail="Category name is required.")
        updates["slug"] = category_slug(updates["name"])
    updates["updatedAt"] = now_utc()
    try:
        updated = await db[CATEGORY_COLLECTION].find_one_and_update({"_id": oid}, {"$set": updates}, return_document=ReturnDocument.AFTER)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail="A category with that name already exists.") from exc
    moved = 0
    if "name" in updates and updates["name"] != existing.get("name"):
        # Books store the category by name, so a rename carries its books along.
        moved = (await db.books.update_many({"category": existing.get("name")}, {"$set": {"category": updates["name"], "updatedAt": now_utc()}})).modified_count
    await audit(user, "update", "category", category_id, {"fields": sorted(payload.model_dump(exclude_unset=True)), "booksMoved": moved}, request_ip(request))
    return {"category": serialize(updated), "booksMoved": moved}


@app.delete("/api/admin/categories/{category_id}", status_code=204)
async def admin_delete_category(category_id: str, request: Request, user: dict[str, Any] = Depends(require_permission("books:write"))):
    oid = require_object_id(category_id, "category")
    existing = await db[CATEGORY_COLLECTION].find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found.")
    in_use = await db.books.count_documents({"category": existing.get("name")})
    if in_use:
        raise HTTPException(status_code=409, detail=f"{in_use} book{'s' if in_use != 1 else ''} still use this category. Move them to another category first.")
    await db[CATEGORY_COLLECTION].delete_one({"_id": oid})
    await audit(user, "delete", "category", category_id, ip=request_ip(request))
    return Response(status_code=204)


@app.get("/api/admin/audit", dependencies=[Depends(require_permission("users:manage"))])
async def audit_log():
    events = await db[AUDIT_COLLECTION].find().sort("createdAt", -1).limit(200).to_list(200)
    user_ids = list({event["user"] for event in events if isinstance(event.get("user"), ObjectId)})
    actors = {
        row["_id"]: {"email": decrypt_text(row.get("email", "")), "role": row.get("role", "")}
        for row in await db.users.find({"_id": {"$in": user_ids}}, {"email": 1, "role": 1}).to_list(len(user_ids) or 1)
    }
    for event in events:
        if event.get("user") in actors:
            event["user"] = actors[event["user"]]
    return {"events": [serialize(event) for event in events]}



BACKUP_FILENAME = "binodmahato_backup_data.zip"
BACKUP_FORMAT = "binodmahato-backup"
BACKUP_VERSION = 1
BACKUP_ZIP_CONTENT_TYPES = {"application/zip", "application/x-zip-compressed", "application/octet-stream"}
BACKUP_MAX_ENTRIES = 2000
BACKUP_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
BACKUP_MAX_COLLECTION_BYTES = 256 * 1024 * 1024
BACKUP_MAX_DOCUMENT_DEPTH = 40
BACKUP_IMAGE_LIMIT = 300
BACKUP_IMAGE_MAX_BYTES = 10 * 1024 * 1024
BACKUP_IMAGES_TOTAL_BYTES = 100 * 1024 * 1024
BACKUP_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/avif": "avif", "image/svg+xml": "svg"}
# Image copies restored from backups, served at /api/media/files/<name> when an original link breaks.
RESTORED_IMAGE_COLLECTION = "backupimages"
SERVED_IMAGE_PREFIX = "/api/media/files/"
SERVED_IMAGE_NAME = re.compile(r"[a-f0-9]{24}\.(?:jpg|png|webp|gif|avif|svg)")
# Login sessions are short-lived and tied to this server; restoring them could revive revoked logins.
# Restored image copies travel in the archive's images/ folder rather than as database JSON.
BACKUP_EXCLUDED_COLLECTIONS = {"auth_sessions", RESTORED_IMAGE_COLLECTION}
BACKUP_COLLECTION_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
BACKUP_ENTRY_PATTERN = re.compile(r"manifest\.json|manifest\.sig|README\.txt|images/index\.json|database/[A-Za-z][A-Za-z0-9_-]{0,63}\.json|images/[a-f0-9]{24}\.[a-z]{3,4}")
BACKUP_JSON_OPTIONS = JSONOptions(json_mode=JSONMode.RELAXED, tz_aware=True, tzinfo=UTC)
# Signed with a key derived from both data secrets: a backup only restores on a server that can
# decrypt its encrypted fields and match its email index, and a tampered archive is rejected.
BACKUP_SIGNING_KEY = hmac.new(EMAIL_INDEX_SECRET, b"backup-signing-v1:" + _fernet_key, hashlib.sha256).digest()
BACKUP_KEY_FINGERPRINT = hmac.new(BACKUP_SIGNING_KEY, b"fingerprint", hashlib.sha256).hexdigest()[:16]
BACKUP_README = """Binod Mahato website backup
===========================

This archive was created from the Admin Panel (Backup & restore) and can only be restored
there, on a server configured with the same DATA_ENCRYPTION_KEY and EMAIL_INDEX_SECRET.

  manifest.json        Backup details, document counts, and SHA-256 checksums of every file.
  manifest.sig         HMAC-SHA256 signature. Any edit to the archive makes it unrestorable.
  database/*.json      Every database collection (books, users, orders, payments, customers,
                       reviews, categories, website content, media, settings, newsletter,
                       notifications, activity log) in MongoDB Extended JSON.
  images/              Copies of the book covers, gallery and website images, with index.json
                       mapping each original URL to its file.

Personal details stay encrypted exactly as they are in the database, and passwords are stored
only as one-way hashes. Still, keep this file private and store it somewhere safe.
"""

_restore_lock = asyncio.Lock()


def backup_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def backup_signature(manifest_bytes: bytes) -> str:
    return hmac.new(BACKUP_SIGNING_KEY, manifest_bytes, hashlib.sha256).hexdigest()


async def backup_collection_names() -> list[str]:
    names = await db.list_collection_names(filter={"type": "collection"})
    return sorted(
        name for name in names
        if BACKUP_COLLECTION_PATTERN.fullmatch(name) and name not in BACKUP_EXCLUDED_COLLECTIONS
    )


async def dump_collections(names: list[str] | set[str]) -> dict[str, list[dict[str, Any]]]:
    return {name: await db[name].find().sort("_id", 1).to_list(None) for name in sorted(names)}


def backup_image_urls(collections: dict[str, list[dict[str, Any]]]) -> list[str]:
    candidates: list[Any] = [book.get("image") for book in collections.get("books", [])]
    candidates += [item.get("url") for item in collections.get(MEDIA_COLLECTION, [])]
    for item in collections.get(CONTENT_COLLECTION, []):
        value = item.get("value")
        if isinstance(value, dict):
            candidates += [value.get(key) for key in ("portrait", "landscape", "ogImage")]
    urls = list(dict.fromkeys(
        url for url in candidates
        if isinstance(url, str) and (url.startswith("https://") or served_image_name(url)) and len(url) <= 2048
    ))
    return urls[:BACKUP_IMAGE_LIMIT]


def served_image_name(url: Any) -> str | None:
    """Returns the file name when url points at an image copy this site serves itself."""
    if not isinstance(url, str):
        return None
    try:
        path = urlparse(url).path
    except ValueError:
        return None
    name = path[len(SERVED_IMAGE_PREFIX):] if path.startswith(SERVED_IMAGE_PREFIX) else ""
    return name if SERVED_IMAGE_NAME.fullmatch(name) else None


def served_image_url(name: str) -> str:
    # Absolute HTTPS address in production, so restored links still pass the media URL rules.
    return f"{API_PUBLIC_URL or WEBSITE_URL}{SERVED_IMAGE_PREFIX}{name}"


async def host_is_public(hostname: str) -> bool:
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return False
    try:
        return bool(addresses) and all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in addresses)
    except ValueError:
        return False


async def fetch_backup_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    # Image URLs are admin-entered, so every hop must resolve to a public address (no SSRF into
    # the server's network), must really be an image, and must stay under the size limit.
    current = url
    for _ in range(4):
        try:
            parsed = urlparse(current)
            hostname = parsed.hostname
        except ValueError:
            return None
        if parsed.scheme != "https" or not hostname or parsed.username or parsed.password or not await host_is_public(hostname):
            return None
        async with client.stream("GET", current) as response:
            if response.is_redirect:
                location = response.headers.get("location", "")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if response.status_code != 200 or content_type not in BACKUP_IMAGE_TYPES:
                return None
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > BACKUP_IMAGE_MAX_BYTES:
                return None
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > BACKUP_IMAGE_MAX_BYTES:
                    return None
                chunks.append(chunk)
            return b"".join(chunks), content_type
    return None


async def collect_backup_images(urls: list[str]) -> tuple[dict[str, bytes], dict[str, Any]]:
    files: dict[str, bytes] = {}
    index: dict[str, Any] = {"images": {}, "skipped": []}
    if not urls:
        return files, index
    semaphore = asyncio.Semaphore(6)

    async def fetch(client: httpx.AsyncClient, url: str) -> tuple[str, tuple[bytes, str] | None]:
        if name := served_image_name(url):
            # A copy this site already serves is read from the database, not over the network.
            stored = await db[RESTORED_IMAGE_COLLECTION].find_one({"_id": name})
            return url, (bytes(stored["data"]), stored["contentType"]) if stored else None
        async with semaphore:
            try:
                return url, await fetch_backup_image(client, url)
            except (httpx.HTTPError, OSError):
                return url, None

    async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(15.0), headers={"User-Agent": "AuthorPortfolioBackup/1.0"}) as client:
        results = await asyncio.gather(*(fetch(client, url) for url in urls))
    total = 0
    for url, result in results:
        if not result or total + len(result[0]) > BACKUP_IMAGES_TOTAL_BYTES:
            index["skipped"].append(url)
            continue
        data, content_type = result
        total += len(data)
        path = f"images/{backup_digest(url.encode('utf-8'))[:24]}.{BACKUP_IMAGE_TYPES[content_type]}"
        files[path] = data
        index["images"][url] = {"file": path, "contentType": content_type, "bytes": len(data)}
    return files, index


async def build_backup_archive(user: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    collections = await dump_collections(await backup_collection_names())
    images, image_index = await collect_backup_images(backup_image_urls(collections))
    files: dict[str, bytes] = {"README.txt": BACKUP_README.encode("utf-8")}
    for name, documents in collections.items():
        files[f"database/{name}.json"] = json_util.dumps(documents, json_options=BACKUP_JSON_OPTIONS, indent=1).encode("utf-8")
    files["images/index.json"] = json.dumps(image_index, indent=1).encode("utf-8")
    files.update(images)
    manifest = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "createdAt": now_utc().isoformat(),
        "createdByRole": user.get("role", ""),
        "app": f"{app.title} {app.version}",
        "keyFingerprint": BACKUP_KEY_FINGERPRINT,
        "collections": {name: {"file": f"database/{name}.json", "documents": len(documents)} for name, documents in collections.items()},
        "images": {"saved": len(image_index["images"]), "skipped": len(image_index["skipped"])},
        "files": {path: {"sha256": backup_digest(data), "bytes": len(data)} for path, data in sorted(files.items())},
    }
    manifest_bytes = json.dumps(manifest, indent=1).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("manifest.sig", backup_signature(manifest_bytes))
        for path, data in sorted(files.items()):
            # Images are already compressed; storing them avoids wasted CPU.
            stored = path.startswith("images/") and path != "images/index.json"
            archive.writestr(path, data, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    return buffer.getvalue(), manifest


def backup_error(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=f"Backup rejected: {message}")


def read_backup_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    # Read at most limit + 1 bytes so a forged size header cannot inflate past the limit.
    try:
        with archive.open(info) as handle:
            data = handle.read(limit + 1)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError, ValueError, EOFError) as exc:
        raise backup_error(f"{info.filename} is damaged.") from exc
    if len(data) > limit or len(data) != info.file_size:
        raise backup_error(f"{info.filename} has an unexpected size.")
    return data


def validate_backup_value(value: Any, depth: int = 0) -> None:
    if depth > BACKUP_MAX_DOCUMENT_DEPTH:
        raise ValueError("documents are nested too deeply")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key or key.startswith("$") or "\x00" in key:
                raise ValueError("documents contain an invalid field name")
            validate_backup_value(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            validate_backup_value(item, depth + 1)


def parse_backup_collection(name: str, data: bytes, expected_count: int) -> list[dict[str, Any]]:
    try:
        documents = json_util.loads(data.decode("utf-8"), json_options=BACKUP_JSON_OPTIONS)
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        raise backup_error(f"the {name} data is not valid JSON.") from exc
    if not isinstance(documents, list) or len(documents) != expected_count:
        raise backup_error(f"the {name} data does not match the manifest.")
    seen_ids: set[str] = set()
    for document in documents:
        if not isinstance(document, dict) or "_id" not in document:
            raise backup_error(f"the {name} data contains a record without an id.")
        try:
            validate_backup_value(document)
        except (ValueError, RecursionError) as exc:
            raise backup_error(f"the {name} data is invalid ({exc}).") from exc
        record_id = json_util.dumps(document["_id"])
        if record_id in seen_ids:
            raise backup_error(f"the {name} data contains duplicate records.")
        seen_ids.add(record_id)
    if name == "users" and any(document.get("role", "customer") not in VALID_ROLES | {"customer"} for document in documents):
        raise backup_error("the users data contains an unknown role.")
    return documents


def read_backup_archive(data: bytes) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    manifest, collections, _ = read_backup_contents(data)
    return manifest, collections


def read_backup_contents(data: bytes) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, bytes]]:
    """Fully verifies an uploaded archive and returns its manifest, collections, and image files."""
    if not data:
        raise backup_error("the uploaded file is empty.")
    if len(data) > BACKUP_MAX_UPLOAD_BYTES:
        raise backup_error("the file is larger than 200 MB.")
    if not data.startswith(b"PK\x03\x04"):
        raise backup_error(f"choose the {BACKUP_FILENAME} file created by this Admin Panel.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError) as exc:
        raise backup_error("the ZIP file is damaged or incomplete.") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > BACKUP_MAX_ENTRIES:
            raise backup_error("the archive contains too many files.")
        entries: dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in infos:
            name = info.filename
            # Exact allow-list of names: blocks path traversal, absolute paths, and stray files.
            if not BACKUP_ENTRY_PATTERN.fullmatch(name) or name in entries:
                raise backup_error("the archive contains unexpected files.")
            if info.flag_bits & 0x1:
                raise backup_error("encrypted ZIP entries are not supported.")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise backup_error("the archive uses an unsupported compression method.")
            if info.file_size > 1024 * 1024 and info.file_size > 200 * max(info.compress_size, 1):
                raise backup_error("the archive is suspiciously compressed.")
            total_size += info.file_size
            if total_size > BACKUP_MAX_UNCOMPRESSED_BYTES:
                raise backup_error("the archive expands beyond the allowed size.")
            entries[name] = info
        if "manifest.json" not in entries or "manifest.sig" not in entries:
            raise backup_error(f"choose the {BACKUP_FILENAME} file created by this Admin Panel.")
        manifest_bytes = read_backup_member(archive, entries["manifest.json"], 4 * 1024 * 1024)
        signature = read_backup_member(archive, entries["manifest.sig"], 128).decode("ascii", "replace").strip()
        try:
            manifest = json.loads(manifest_bytes)
        except ValueError as exc:
            raise backup_error("the manifest is not valid JSON.") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT:
            raise backup_error(f"choose the {BACKUP_FILENAME} file created by this Admin Panel.")
        if manifest.get("version") != BACKUP_VERSION:
            raise backup_error("this backup version is not supported.")
        if manifest.get("keyFingerprint") != BACKUP_KEY_FINGERPRINT:
            raise backup_error("it was created by a server with different encryption secrets, so its data cannot be read here.")
        if not hmac.compare_digest(signature, backup_signature(manifest_bytes)):
            raise backup_error("the signature does not match. The file was modified or is not a genuine backup.")

        listed = manifest.get("files")
        collections_meta = manifest.get("collections")
        if not isinstance(listed, dict) or not isinstance(collections_meta, dict):
            raise backup_error("the manifest is incomplete.")
        if set(listed) != set(entries) - {"manifest.json", "manifest.sig"}:
            raise backup_error("the archive contents do not match the manifest.")
        database_files: dict[str, bytes] = {}
        image_files: dict[str, bytes] = {}
        for path, info in entries.items():
            if path in {"manifest.json", "manifest.sig"}:
                continue
            expected = listed[path]
            limit = BACKUP_MAX_COLLECTION_BYTES if path.startswith("database/") else BACKUP_IMAGE_MAX_BYTES + 4 * 1024 * 1024
            content = read_backup_member(archive, info, limit)
            if not isinstance(expected, dict) or not hmac.compare_digest(str(expected.get("sha256", "")), backup_digest(content)):
                raise backup_error(f"{path} failed its integrity check.")
            if path.startswith("database/"):
                database_files[path] = content
            elif path.startswith("images/"):
                image_files[path] = content

    collections: dict[str, list[dict[str, Any]]] = {}
    for name, meta in collections_meta.items():
        path = f"database/{name}.json"
        count = meta.get("documents") if isinstance(meta, dict) else None
        if (
            not isinstance(meta, dict)
            or not BACKUP_COLLECTION_PATTERN.fullmatch(name)
            or name in BACKUP_EXCLUDED_COLLECTIONS
            or meta.get("file") != path
            or path not in database_files
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise backup_error("the manifest lists an invalid collection.")
        collections[name] = parse_backup_collection(name, database_files[path], count)
    if set(database_files) != {f"database/{name}.json" for name in collections}:
        raise backup_error("the archive contents do not match the manifest.")
    if "users" not in collections or "books" not in collections:
        raise backup_error("it does not contain the users and books data.")
    return manifest, collections, image_files


def backup_summary(manifest: dict[str, Any], collections: dict[str, list[dict[str, Any]]], size: int) -> dict[str, Any]:
    images = manifest.get("images") if isinstance(manifest.get("images"), dict) else {}
    return {
        "fileName": BACKUP_FILENAME,
        "createdAt": manifest.get("createdAt"),
        "bytes": size,
        "collections": {name: len(documents) for name, documents in collections.items()},
        "documents": sum(len(documents) for documents in collections.values()),
        "images": images.get("saved", 0),
    }


async def read_backup_upload(request: Request) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, bytes], int]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in BACKUP_ZIP_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail=f"Upload the {BACKUP_FILENAME} file as a ZIP archive.")
    data = await request.body()
    manifest, collections, image_files = await asyncio.to_thread(read_backup_contents, data)
    return manifest, collections, image_files, len(data)


def backup_image_index(image_files: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    try:
        index = json.loads(image_files.get("images/index.json", b"{}"))
    except ValueError:
        return {}
    images = index.get("images") if isinstance(index, dict) else None
    if not isinstance(images, dict):
        return {}
    return {
        url: meta for url, meta in images.items()
        if isinstance(url, str) and isinstance(meta, dict) and meta.get("file") in image_files
        and meta.get("contentType") in BACKUP_IMAGE_TYPES
    }


async def original_image_available(client: httpx.AsyncClient, url: str) -> bool:
    try:
        return await fetch_backup_image(client, url) is not None
    except (httpx.HTTPError, OSError):
        return False


async def store_restored_image(name: str, data: bytes, content_type: str, source: str) -> None:
    await db[RESTORED_IMAGE_COLLECTION].update_one(
        {"_id": name},
        {"$set": {"data": data, "contentType": content_type, "bytes": len(data), "sourceUrl": source[:2048], "updatedAt": now_utc()}},
        upsert=True,
    )


async def repair_restored_images(image_files: dict[str, bytes]) -> dict[str, int]:
    """Puts backed-up images back where their links are broken; working links are left alone."""
    index = backup_image_index(image_files)
    result = {"checked": len(index), "kept": 0, "repaired": 0, "unreferenced": 0}
    if not index:
        return result
    semaphore = asyncio.Semaphore(6)

    async def check(client: httpx.AsyncClient, url: str) -> tuple[str, bool]:
        if served_image_name(url):
            return url, False
        async with semaphore:
            return url, await original_image_available(client, url)

    async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(10.0), headers={"User-Agent": "AuthorPortfolioBackup/1.0"}) as client:
        checks = await asyncio.gather(*(check(client, url) for url in index))
    for url, available in checks:
        meta = index[url]
        data = image_files[meta["file"]]
        if available:
            result["kept"] += 1
            continue
        if existing := served_image_name(url):
            # Already a copy served by this site: put the file back under the same name.
            await store_restored_image(existing, data, meta["contentType"], url)
            result["kept"] += 1
            continue
        name = f"{backup_digest(data)[:24]}.{BACKUP_IMAGE_TYPES[meta['contentType']]}"
        await store_restored_image(name, data, meta["contentType"], url)
        replacement = served_image_url(name)
        changed = (await db.books.update_many({"image": url}, {"$set": {"image": replacement}})).modified_count
        changed += (await db[MEDIA_COLLECTION].update_many({"url": url}, {"$set": {"url": replacement}})).modified_count
        for field in ("portrait", "landscape", "ogImage"):
            changed += (await db[CONTENT_COLLECTION].update_many({f"value.{field}": url}, {"$set": {f"value.{field}": replacement}})).modified_count
        result["repaired" if changed else "unreferenced"] += 1
    return result


@app.get(SERVED_IMAGE_PREFIX + "{name}")
async def restored_image(name: str):
    if not SERVED_IMAGE_NAME.fullmatch(name):
        raise HTTPException(status_code=404, detail="Image not found.")
    image = await db[RESTORED_IMAGE_COLLECTION].find_one({"_id": name})
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")
    return Response(content=bytes(image["data"]), media_type=image["contentType"], headers={
        # The name is derived from the file's contents, so it never changes and can be cached for good.
        "Cache-Control": "public, max-age=31536000, immutable",
        # Sandboxed so an uploaded SVG can never run scripts on this origin.
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    })


async def replace_collections(collections: dict[str, list[dict[str, Any]]]) -> None:
    for name, documents in collections.items():
        await db[name].delete_many({})
        if documents:
            await db[name].insert_many(documents, ordered=True)


async def keep_restoring_admin(admin: dict[str, Any]) -> None:
    # The restoring administrator keeps their current account, so a restore can never lock them
    # out (for example with an older password, or a backup that lacks their admin account).
    conflicts: list[dict[str, Any]] = [{"_id": admin["_id"]}]
    if admin.get("emailHash"):
        conflicts.append({"emailHash": admin["emailHash"]})
    await db.users.delete_many({"$or": conflicts})
    await db.users.insert_one(admin)
    await db.app_metadata.update_one(
        {"_id": "bootstrap-admin"},
        {"$set": {"user": admin["_id"], "emailVerificationEnforced": True}, "$setOnInsert": {"createdAt": now_utc()}},
        upsert=True,
    )


@app.get("/api/admin/backup")
async def download_backup(request: Request, user: dict[str, Any] = Depends(require_permission("backup:manage"))):
    data, manifest = await build_backup_archive(user)
    await audit(user, "export", "backup", "", {
        "documents": sum(item["documents"] for item in manifest["collections"].values()),
        "images": manifest["images"]["saved"],
        "bytes": len(data),
    }, request_ip(request))
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{BACKUP_FILENAME}"'},
    )


@app.post("/api/admin/backup/verify")
async def verify_backup(request: Request, _: dict[str, Any] = Depends(require_permission("backup:manage"))):
    manifest, collections, _, size = await read_backup_upload(request)
    return {"backup": backup_summary(manifest, collections, size)}


@app.post("/api/admin/backup/restore")
async def restore_backup(request: Request, user: dict[str, Any] = Depends(require_permission("backup:manage"))):
    if request.headers.get("x-confirm-restore") != "RESTORE":
        raise HTTPException(status_code=400, detail="Confirm the restore before replacing the website data.")
    if _restore_lock.locked():
        raise HTTPException(status_code=409, detail="A restore is already running. Please wait for it to finish.")
    async with _restore_lock:
        manifest, collections, image_files, size = await read_backup_upload(request)
        # Collections created after the backup was taken are emptied, so the site matches the
        # backup exactly. The snapshot lets a failed restore put everything back as it was.
        affected = set(collections) | set(await backup_collection_names())
        snapshot = await dump_collections(affected)
        try:
            await replace_collections({name: collections.get(name, []) for name in sorted(affected)})
            await keep_restoring_admin(user)
        except Exception as exc:
            logger.exception("Backup restore failed; rolling back to the previous data.")
            try:
                await replace_collections(snapshot)
            except Exception:
                logger.critical("Rollback after a failed restore also failed; restore the pre-restore backup manually.", exc_info=True)
                raise HTTPException(status_code=500, detail="The restore failed and the previous data could not be fully put back. Restore your most recent backup file.") from exc
            raise HTTPException(status_code=500, detail="The restore failed, so the previous data was kept unchanged.") from exc
        # Restored accounts may differ from the current ones, so every other login is signed out.
        await db.auth_sessions.delete_many({"tokenHash": {"$ne": getattr(request.state, "session_hash", "")}})
        _maintenance_cache.update(state=None, expires=0.0)
        summary = backup_summary(manifest, collections, size)
        try:
            summary["imageRestore"] = await repair_restored_images(image_files)
        except Exception:  # noqa: BLE001 - the data is already restored; image repair is best effort
            logger.exception("Restored data is in place, but backed-up images could not be checked.")
            summary["imageRestore"] = {"checked": 0, "kept": 0, "repaired": 0, "unreferenced": 0, "failed": True}
    await audit(user, "restore", "backup", "", {"documents": summary["documents"], "backupCreatedAt": summary["createdAt"]}, request_ip(request))
    return {"restored": True, "backup": summary}
