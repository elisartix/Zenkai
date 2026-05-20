import json
import logging
import os
import secrets
import string

logger = logging.getLogger(__name__)

CREDENTIALS_FILE = "web_credentials.json"


class WebCredentials:
    def __init__(self, data_root="."):
        self.data_root = data_root
        self.path = os.path.join(data_root, CREDENTIALS_FILE)
        self.username = ""
        self.password = ""
        self.auth_key = ""
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self.username = data.get("username", "")
                self.password = data.get("password", "")
                self.auth_key = data.get("auth_key", "")
                if self.username and self.password and self.auth_key:
                    return
            except (OSError, json.JSONDecodeError):
                logger.warning("Web credentials are broken, regenerating")

        self._generate()
        self._save()

    def _generate(self):
        alphabet = string.ascii_letters + string.digits
        self.username = "admin_" + "".join(
            secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)
        )
        self.password = "".join(secrets.choice(alphabet) for _ in range(24))
        self.auth_key = secrets.token_urlsafe(32)

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "username": self.username,
                    "password": self.password,
                    "auth_key": self.auth_key,
                },
                handle,
                indent=2,
            )

    def log_credentials(self, port=8080):
        login_url = f"http://localhost:{port}/"
        dashboard_url = f"http://localhost:{port}/dashboard"
        message = (
            "\n"
            "[ Zenkai Web Dashboard Credentials ]\n"
            f"Username:  {self.username}\n"
            f"Password:  {self.password}\n"
            f"Auth Key:  {self.auth_key}\n"
            f"Login:     {login_url}\n"
            f"Dashboard: {dashboard_url}\n"
        )
        print(message)
        logger.info("Web dashboard credentials ready. Username: %s", self.username)
