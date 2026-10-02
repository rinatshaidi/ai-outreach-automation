"""Provider-neutral email adapter with a standard-library SMTP implementation."""

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Protocol

from app.config import Settings


class DeliveryProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeliveryReceipt:
    message_id: str
    thread_id: str | None = None


class EmailDeliveryAdapter(Protocol):
    provider_name: str

    async def send(
        self, *, recipient: str, subject: str, body: str
    ) -> str | DeliveryReceipt: ...


class SmtpDeliveryAdapter:
    provider_name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send(self, *, recipient: str, subject: str, body: str) -> DeliveryReceipt:
        return await asyncio.to_thread(self._send_sync, recipient, subject, body)

    def _send_sync(self, recipient: str, subject: str, body: str) -> DeliveryReceipt:
        message = EmailMessage()
        message_id = make_msgid(domain="local.outreach")
        message["Message-ID"] = message_id
        message["From"] = formataddr((self.settings.smtp_from_name, self.settings.smtp_from_email))
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=10,
            ) as smtp:
                if self.settings.smtp_use_tls:
                    smtp.starttls()
                if self.settings.smtp_username and self.settings.smtp_password:
                    smtp.login(
                        self.settings.smtp_username.get_secret_value(),
                        self.settings.smtp_password.get_secret_value(),
                    )
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise DeliveryProviderError(type(exc).__name__) from exc
        return DeliveryReceipt(message_id=message_id)
