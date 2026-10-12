"""Gmail SMTP sending. Refuses to do anything unless approved is exactly True."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .. import config, security


class EmailError(RuntimeError):
    pass


class EmailNotConfigured(EmailError):
    pass


def smtp_configured() -> bool:
    return config.has("SMTP_USER") and config.has("SMTP_APP_PASSWORD")


def send_email(to: str, subject: str, body: str, approved: bool,
               limiter: security.SendLimiter | None = None) -> None:
    """Send one plain-text email. `approved` must be the boolean True (set by the Approve button)."""
    if approved is not True:
        raise EmailError("Email was not approved by the user.")
    to = security.validate_recipient(to)
    subject = security.validate_subject(subject)
    body = security.validate_body(body)
    if limiter:
        limiter.check()
    if not smtp_configured():
        raise EmailNotConfigured("SMTP_USER and SMTP_APP_PASSWORD are not set in .env.")
    user = config.env("SMTP_USER")
    msg = EmailMessage()
    msg["From"] = user  # always the configured account
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)  # plain text only
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
            s.login(user, config.env("SMTP_APP_PASSWORD"))
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise EmailError("Gmail rejected the login. Use an app password (needs 2-step verification).")
    except (smtplib.SMTPException, OSError):
        raise EmailError("Could not send the email. Check your connection and try again.")
    if limiter:
        limiter.record()
