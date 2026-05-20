import asyncio
import hashlib
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = REPO_ROOT / ".venv"
STAMP_FILE = VENV_DIR / ".zenkai_requirements.sha256"


def _venv_python():
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _run(command, **kwargs):
    return subprocess.run(
        [str(part) for part in command],
        cwd=str(REPO_ROOT),
        check=True,
        **kwargs,
    )


def _requirements_hash(requirements):
    digest = hashlib.sha256()
    digest.update(requirements.read_bytes())
    digest.update(sys.version.encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def _ensure_venv():
    if os.environ.get("ZENKAI_NO_VENV"):
        return

    venv_python = _venv_python()
    try:
        if venv_python.exists() and Path(sys.executable).resolve() == venv_python.resolve():
            return
    except OSError:
        pass

    try:
        if not venv_python.exists():
            print("Zenkai: creating local virtual environment...")
            _run([sys.executable, "-m", "venv", str(VENV_DIR)])

        env = os.environ.copy()
        env["ZENKAI_BOOTSTRAPPED"] = "1"
        os.execve(str(venv_python), [str(venv_python), "-m", "Zenkai", *sys.argv[1:]], env)
    except Exception as error:
        print(f"Zenkai: could not use .venv ({error}); trying current Python.")


def _ensure_pip():
    try:
        _run([sys.executable, "-m", "pip", "--version"], stdout=subprocess.DEVNULL)
        return
    except Exception:
        pass

    try:
        print("Zenkai: installing pip...")
        _run([sys.executable, "-m", "ensurepip", "--upgrade"])
    except Exception as error:
        raise RuntimeError("pip is not available and ensurepip failed") from error


def _install_requirements():
    if os.environ.get("ZENKAI_SKIP_DEPS"):
        return

    requirements = REPO_ROOT / "requirements.txt"
    if not requirements.exists():
        return

    current_hash = _requirements_hash(requirements)
    if STAMP_FILE.exists() and STAMP_FILE.read_text(encoding="utf-8").strip() == current_hash:
        return

    _ensure_pip()
    print("Zenkai: installing dependencies from requirements.txt...")
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            "-r",
            str(requirements),
        ]
    )

    STAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STAMP_FILE.write_text(current_hash, encoding="utf-8")


def _launch():
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    _ensure_venv()
    _install_requirements()

    from main import main

    asyncio.run(main())


if __name__ == "__main__":
    _launch()

