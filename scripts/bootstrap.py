"""Generate local demo secrets. No third-party dependencies required."""
from pathlib import Path
import base64
import os
import secrets

if __name__ == "__main__":
    target = Path(".env")
    if target.exists():
        raise SystemExit(".env already exists; refusing to replace secrets")
    password = secrets.token_urlsafe(20)
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    template = Path(".env.example").read_text()
    content = template.replace("ADMIN_PASSWORD=\n", f"ADMIN_PASSWORD={password}\n").replace("PII_ENCRYPTION_KEY=\n", f"PII_ENCRYPTION_KEY={key}\n")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content)
    print("Created .env for LOCAL DEMO. Login: admin")
    print(f"Password: {password}")
    print("Do not share .env. Do not publicly deploy this demo configuration.")
