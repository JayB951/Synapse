import os
import smtplib
from email.message import EmailMessage
from datetime import datetime
from zoneinfo import ZoneInfo


def main():
    sender = os.getenv("MAIL_USERNAME")
    password = os.getenv("MAIL_PASSWORD")
    recipient = os.getenv("WORLD_SHARDS_NOTIFY_EMAIL")

    missing = [
        name for name, value in (
            ("MAIL_USERNAME", sender),
            ("MAIL_PASSWORD", password),
            ("WORLD_SHARDS_NOTIFY_EMAIL", recipient),
        ) if not value
    ]
    if missing:
        raise RuntimeError("Hiányzó GitHub Secret(ek): " + ", ".join(missing))

    now = datetime.now(ZoneInfo("Europe/Budapest"))
    message = EmailMessage()
    message["Subject"] = f"WORLD SHARDS – e-mail teszt ({now:%Y-%m-%d %H:%M})"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        "Ez egy automatikus tesztüzenet a WORLD SHARDS e-mailküldő rendszeréből.\n\n"
        "Ha ezt az üzenetet megkaptad, a Gmail SMTP-hitelesítés és a címzett beállítása működik.\n"
        "Ez a teszt nem olvas és nem módosít magazinkiadványt."
    )
    message.add_alternative(
        """<!doctype html><html><body style="font-family:Arial,sans-serif;color:#182538">
        <h2>WORLD SHARDS – e-mail teszt</h2>
        <p>Ha ezt az üzenetet megkaptad, a Gmail SMTP-hitelesítés és a címzett beállítása működik.</p>
        <p>Ez a teszt nem olvas és nem módosít magazinkiadványt.</p>
        </body></html>""",
        subtype="html",
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)

    print("SMTP_TEST=SUCCESS")
    print("SENDER=" + sender)
    print("RECIPIENT=" + recipient)


if __name__ == "__main__":
    main()
