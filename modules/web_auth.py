import html
import json
import os

from core.module import Module, command


class WebAuthModule(Module):
    name = "WebAuth"
    description = "Shows Web Dashboard credentials and auth links."

    def _credentials(self):
        path = "web_credentials.json"
        if not os.path.exists(path):
            return None

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return None

        if not all(data.get(key) for key in ("username", "password", "auth_key")):
            return None
        return data

    @command(name="auth", description="Show Web Dashboard auth link.")
    async def auth_cmd(self, event):
        creds = self._credentials()
        if not creds:
            return await event.edit("Web Dashboard credentials are not ready yet.")

        args = event.raw_text.split(maxsplit=1)
        key = args[1].strip() if len(args) > 1 else creds["auth_key"]
        if key != creds["auth_key"]:
            return await event.edit("Invalid Web Dashboard auth key.")

        url = f"http://localhost:8080/api/auth_key_login/{creds['auth_key']}"
        await event.edit(
            "Zenkai Web Dashboard\n\n"
            f"Login: <code>http://localhost:8080/</code>\n"
            f"One-click auth: <a href=\"{html.escape(url)}\">open dashboard</a>",
            parse_mode="html",
            link_preview=False,
        )

    @command(name="webcreds", description="Show Web Dashboard login credentials.")
    async def webcreds_cmd(self, event):
        creds = self._credentials()
        if not creds:
            return await event.edit("Web Dashboard credentials are not ready yet.")

        await event.edit(
            "Zenkai Web Dashboard credentials\n\n"
            f"Username: <code>{html.escape(creds['username'])}</code>\n"
            f"Password: <code>{html.escape(creds['password'])}</code>\n"
            f"Auth Key: <code>{html.escape(creds['auth_key'])}</code>",
            parse_mode="html",
            link_preview=False,
        )
