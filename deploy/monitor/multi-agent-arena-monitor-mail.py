#!/usr/bin/env python3

import argparse
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List


def load_env(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid mail configuration line")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in key):
            raise ValueError("invalid mail configuration key")
        values[key] = value.strip()
    return values


def recipients(value: str) -> List[str]:
    result = [item.strip() for item in value.replace(";", ",").split(",")]
    result = [item for item in result if item]
    if not result:
        raise ValueError("ALERT_TO must contain at least one recipient")
    return result


def send_mail(config: Dict[str, str], subject: str, body: str) -> int:
    required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_FROM", "ALERT_TO")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"mail configuration missing: {','.join(missing)}")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["ALERT_FROM"]
    target_addresses = recipients(config["ALERT_TO"])
    message["To"] = ", ".join(target_addresses)
    message.set_content(body)

    host = config["SMTP_HOST"]
    port = int(config.get("SMTP_PORT", "465"))
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
        server.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
        server.send_message(message)
    return len(target_addresses)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a monitor alert email over SMTP SSL")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--subject", required=True)
    args = parser.parse_args()

    try:
        config = load_env(args.config)
        count = send_mail(config, args.subject, sys.stdin.read())
    except (OSError, ValueError, smtplib.SMTPException) as error:
        print(f"mail_send_failed reason={error.__class__.__name__}", file=sys.stderr)
        return 1

    print(f"mail_sent recipient_count={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())