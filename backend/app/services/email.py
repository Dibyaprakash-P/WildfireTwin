"""Email delivery abstraction for verification OTPs.

Providers (EMAIL_PROVIDER):
  console   development only: the OTP is printed to the backend *console*
            (stdout) so a developer can complete sign-up locally. It is never
            written to MongoDB, the system log collection or any API response.
  smtp      any SMTP server (SMTP_HOST/PORT/USERNAME/PASSWORD, STARTTLS)
  resend    Resend HTTP API (RESEND_API_KEY)
  sendgrid  SendGrid v3 HTTP API (SENDGRID_API_KEY)
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

import httpx

from backend.app.config import Settings, get_settings

log = logging.getLogger(__name__)


class EmailNotConfigured(RuntimeError):
    pass


def _otp_text(code: str, ttl_s: int) -> tuple[str, str]:
    subject = "WildfireTwin verification code"
    body = (f"Your WildfireTwin verification code is: {code}\n\n"
            f"It expires in {ttl_s // 60} minutes. If you did not request it, ignore this email.")
    return subject, body


def mask_email(email: str) -> str:
    name, _, dom = email.partition("@")
    return f"{name[:1]}***@{dom}"


class EmailService(ABC):
    def __init__(self, settings: Settings):
        self.s = settings

    @abstractmethod
    async def send(self, to: str, subject: str, body: str) -> None: ...

    async def send_verification_otp(self, to: str, code: str) -> None:
        subject, body = _otp_text(code, self.s.otp_ttl_seconds)
        await self.send(to, subject, body)


class ConsoleEmailService(EmailService):
    async def send(self, to: str, subject: str, body: str) -> None:
        if self.s.app_env == "production":
            raise EmailNotConfigured("console email provider is not allowed in production")
        print(f"\n[DEV EMAIL] to={to} subject={subject!r}\n{body}\n", flush=True)


class SmtpEmailService(EmailService):
    async def send(self, to: str, subject: str, body: str) -> None:
        if not self.s.smtp_host:
            raise EmailNotConfigured("SMTP_HOST not set")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.email_from, to, subject
        msg.set_content(body)

        def _send():
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
                if self.s.smtp_starttls:
                    smtp.starttls()
                if self.s.smtp_username:
                    smtp.login(self.s.smtp_username, self.s.smtp_password)
                smtp.send_message(msg)

        await asyncio.to_thread(_send)


class ResendEmailService(EmailService):
    async def send(self, to: str, subject: str, body: str) -> None:
        if not self.s.resend_api_key:
            raise EmailNotConfigured("RESEND_API_KEY not set")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {self.s.resend_api_key}"},
                             json={"from": self.s.email_from, "to": [to], "subject": subject, "text": body})
            r.raise_for_status()


class SendGridEmailService(EmailService):
    async def send(self, to: str, subject: str, body: str) -> None:
        if not self.s.sendgrid_api_key:
            raise EmailNotConfigured("SENDGRID_API_KEY not set")
        sender = self.s.email_from.split("<")[-1].rstrip(">").strip()
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post("https://api.sendgrid.com/v3/mail/send",
                             headers={"Authorization": f"Bearer {self.s.sendgrid_api_key}"},
                             json={"personalizations": [{"to": [{"email": to}]}], "from": {"email": sender},
                                   "subject": subject, "content": [{"type": "text/plain", "value": body}]})
            r.raise_for_status()


def get_email_service() -> EmailService:
    s = get_settings()
    return {"console": ConsoleEmailService, "smtp": SmtpEmailService,
            "resend": ResendEmailService, "sendgrid": SendGridEmailService}[s.email_provider](s)
