import asyncio
import os
import subprocess
import sys
from pathlib import Path

from core.module import Module, command


class UpdaterModule(Module):
    name = "Updater"
    description = "Updates Zenkai from GitHub."

    REPO_URL = "https://github.com/elisartix/Zenkai.git"

    def _repo_dir(self):
        return Path(__file__).resolve().parents[1]

    async def _run(self, *args, timeout=180):
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(self._repo_dir()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError(f"`{' '.join(args)}` timed out")

        output = (stdout + stderr).decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise RuntimeError(output or f"`{' '.join(args)}` failed")
        return output

    async def _ensure_origin(self):
        try:
            current = (await self._run("git", "remote", "get-url", "origin")).strip()
        except RuntimeError:
            await self._run("git", "remote", "add", "origin", self.REPO_URL)
            return

        if current != self.REPO_URL:
            await self._run("git", "remote", "set-url", "origin", self.REPO_URL)

    async def _remote_ref(self):
        try:
            ref = (await self._run("git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")).strip()
            if ref:
                return ref
        except RuntimeError:
            pass

        for ref in ("origin/main", "origin/master"):
            try:
                await self._run("git", "rev-parse", "--verify", ref)
                return ref
            except RuntimeError:
                continue

        raise RuntimeError("В репозитории GitHub пока нет ветки для обновления.")

    async def _install_requirements(self):
        requirements = self._repo_dir() / "requirements.txt"
        if requirements.exists():
            await self._run(
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements),
                "--disable-pip-version-check",
                timeout=900,
            )

    async def _restart(self):
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    @command(name="update", aliases=["up", "selfupdate"], description="Update Zenkai from GitHub.")
    async def update_cmd(self, event):
        raw = getattr(event, "raw_text", "") or ""
        args = raw.split()[1:]
        force = any(arg in {"-f", "--force"} for arg in args)
        no_restart = any(arg in {"--no-restart", "-n"} for arg in args)

        await event.edit("🔄 <b>Проверяю обновления Zenkai...</b>", parse_mode="html")

        if not (self._repo_dir() / ".git").exists():
            return await event.edit(
                "❌ <b>Обновление недоступно:</b> эта установка Zenkai не является git-репозиторием.",
                parse_mode="html",
            )

        try:
            await self._ensure_origin()
            await self._run("git", "fetch", "--prune", "origin")
            remote_ref = await self._remote_ref()
            branch = remote_ref.split("/", 1)[1]

            current = (await self._run("git", "rev-parse", "HEAD")).strip()
            latest = (await self._run("git", "rev-parse", remote_ref)).strip()

            if current == latest and not force:
                return await event.edit("✅ <b>Zenkai уже актуален.</b>", parse_mode="html")

            dirty = await self._run("git", "status", "--porcelain", "--untracked-files=no")
            if dirty.strip():
                return await event.edit(
                    "⚠️ <b>Обновление остановлено:</b> есть локальные изменения в отслеживаемых файлах.\n"
                    "Сохрани или закоммить их, затем запусти <code>.update</code> ещё раз.",
                    parse_mode="html",
                )

            await event.edit("⬇️ <b>Скачиваю обновление из GitHub...</b>", parse_mode="html")
            await self._run("git", "pull", "--ff-only", "origin", branch)
            await self._install_requirements()

            if no_restart:
                return await event.edit(
                    "✅ <b>Zenkai обновлён.</b>\nПерезапуск пропущен из-за <code>--no-restart</code>.",
                    parse_mode="html",
                )

            await event.edit("✅ <b>Zenkai обновлён. Перезапускаюсь...</b>", parse_mode="html")
            await self._restart()
        except Exception as error:
            await event.edit(
                f"❌ <b>Не удалось обновить Zenkai:</b>\n<code>{str(error)[:3500]}</code>",
                parse_mode="html",
            )
