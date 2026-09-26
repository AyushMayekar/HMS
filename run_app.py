"""
Meridian Care Hospital — one-command launcher.

Starts the FastAPI backend (uvicorn) and the Streamlit frontend together,
reusing the shared environment in .env.

Usage:
    python run_app.py                          # default ports (8000 / 8501)
    BACKEND_PORT=8001 STREAMLIT_PORT=8502 python run_app.py   # custom ports
    python run_app.py --status                 # show running processes
    python run_app.py --stop                   # stop both services
"""
from __future__ import annotations

import argparse
import io
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# Windows consoles default to a legacy code page (cp1252/GBK) that cannot
# encode the em-dashes/arrows used in launcher output. Force UTF-8 with a
# safe fallback so the launcher behaves the same on Windows and Linux.
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, AttributeError):  # pragma: no cover - stream closed
        pass
if sys.stdout is None:  # pythonw.exe on Windows has no console
    sys.stdout = io.StringIO()

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "integrated_hospital"
FRONTEND_APP = ROOT / "frontend" / "app.py"
PID_DIR = ROOT / ".run"
PID_FILE = PID_DIR / "app.pids"

BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))


def pick_python() -> Path:
    """Prefer the project venv, fall back to the active interpreter.

    Cross-platform: POSIX venvs live at ``.venv/bin/python`` while Windows
    venvs live at ``.venv/Scripts/python.exe`` — check both, plus the
    optional Linux test venv (``.venv-linux``) used in CI.
    """
    candidates = [
        ROOT / ".venv" / "bin" / "python",
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv-linux" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True if something already accepts connections on host:port.

    Connect-probe, not a bind-probe: on Windows a bind with SO_REUSEADDR
    can silently succeed over a live listener, which made the old check
    report a busy port as free and crash the backend with EADDRINUSE.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def check_imports(python: Path) -> bool:
    """Fail fast with a helpful message if a dependency is missing."""
    checks = {
        "uvicorn": "BACKEND (uvicorn)",
        "streamlit": "FRONTEND (streamlit)",
        "fastapi": "BACKEND (FastAPI)",
        "supabase": "BACKEND (supabase-py)",
    }
    missing = [
        module for module, label in checks.items()
        if subprocess.run([str(python), "-c", f"import {module}"],
                          capture_output=True).returncode != 0
    ]
    if missing:
        print(f"[launcher] Missing dependencies: {', '.join(missing)}.", flush=True)
        print("[launcher] Install with:  uv sync   (or: "
              f"{python} -m pip install streamlit fastapi uvicorn supabase python-dotenv requests)",
              flush=True)
        return False
    return True


def read_pids() -> dict:
    if not PID_FILE.exists():
        return {}
    data: dict = {}
    for line in PID_FILE.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = int(value)
    return data


def write_pids(pids: dict) -> None:
    PID_DIR.mkdir(exist_ok=True)
    PID_FILE.write_text("".join(f"{k}={v}\n" for k, v in pids.items()))


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def cmd_status() -> int:
    pids = read_pids()
    alive = {k: v for k, v in pids.items() if is_alive(v)}
    if not alive:
        print("[status] No Meridian Care processes are running.", flush=True)
        return 0
    for name, pid in alive.items():
        print(f"[status] {name}: running (pid {pid})", flush=True)
    print(f"[status] Backend  : http://127.0.0.1:{BACKEND_PORT}/docs", flush=True)
    print(f"[status] Frontend : http://localhost:{STREAMLIT_PORT}", flush=True)
    return 0


def cmd_stop() -> int:
    pids = read_pids()
    stopped = []
    for name, pid in pids.items():
        if is_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                stopped.append(f"{name} (pid {pid})")
            except OSError as exc:  # noqa: PERF203
                print(f"[stop] Could not stop {name}: {exc}", flush=True)
    if stopped:
        print(f"[stop] Sent stop signal to: {', '.join(stopped)}", flush=True)
    else:
        print("[stop] Nothing running.", flush=True)
    write_pids({})
    return 0


STOP_REQUESTED = False  # set by signal handlers when a termination is requested


def _request_stop(signum, frame):  # noqa: ARG001
    """Raise KeyboardInterrupt from a signal so the finally block cleans up."""
    global STOP_REQUESTED
    STOP_REQUESTED = True
    raise KeyboardInterrupt


def _terminate_children(processes) -> None:
    for proc in processes:
        try:
            proc.terminate()
        except ProcessLookupError:
            continue
    for proc in processes:
        try:
            proc.wait(timeout=10)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                proc.kill()
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Meridian Care launcher")
    parser.add_argument("--status", action="store_true", help="show running processes")
    parser.add_argument("--stop", action="store_true", help="stop both services")
    args = parser.parse_args()

    if args.status:
        return cmd_status()
    if args.stop:
        return cmd_stop()

    python = pick_python()

    print("=" * 70, flush=True)
    print("   Meridian Care Hospital — Application Launcher", flush=True)
    print("=" * 70, flush=True)

    if not check_imports(python):
        return 1

    processes: list[subprocess.Popen] = []
    pids: dict = {}

    # ---- Backend -------------------------------------------------------
    if port_in_use(BACKEND_PORT):
        print(f"[backend] Port {BACKEND_PORT} already in use — assuming an "
              "existing API server and skipping the backend start.")
    else:
        backend_cmd = [
            str(python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--reload",
        ]

        print(f"[backend] Starting API on http://{BACKEND_HOST}:{BACKEND_PORT}  (cwd={BACKEND_DIR})", flush=True)
        proc = subprocess.Popen(backend_cmd, cwd=str(BACKEND_DIR))
        processes.append(proc)
        pids["backend"] = proc.pid

    # ---- Frontend ------------------------------------------------------
    if port_in_use(STREAMLIT_PORT):
        print(f"[frontend] Port {STREAMLIT_PORT} already in use — nothing to do. "
              f"Open http://localhost:{STREAMLIT_PORT} in your browser.")
    else:
        frontend_cmd = [
            str(python), "-m", "streamlit", "run", str(FRONTEND_APP), "--server.runOnSave", "true",
            "--server.port", str(STREAMLIT_PORT),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ]
        print(f"[frontend] Starting Streamlit on http://localhost:{STREAMLIT_PORT}", flush=True)
        proc = subprocess.Popen(frontend_cmd, cwd=str(ROOT))
        processes.append(proc)
        pids["frontend"] = proc.pid

    write_pids(pids)

    if not processes:
        print("[launcher] Both services are already running. Use --status to inspect.", flush=True)
        return 0

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    print(flush=True)
    print(f"  Backend API  : http://127.0.0.1:{BACKEND_PORT}/docs", flush=True)
    print(f"  Frontend app : http://localhost:{STREAMLIT_PORT}", flush=True)
    print("  Press Ctrl+C to stop both.", flush=True)
    print("=" * 70, flush=True)

    try:
        while True:
            for proc in processes:
                if proc.poll() is not None and proc.returncode != 0:
                    print(f"[launcher] A process exited with code {proc.returncode}. Stopping…", flush=True)
                    break
            else:
                time.sleep(1)
                continue
            break
    except KeyboardInterrupt:
        print("\n[launcher] Shutting down…", flush=True)
    finally:
        _terminate_children(processes)
        write_pids({})
    return 0


if __name__ == "__main__":
    sys.exit(main())