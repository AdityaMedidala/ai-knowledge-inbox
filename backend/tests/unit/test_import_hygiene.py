"""Production code must never depend on, or be altered by, test infrastructure."""

import ast
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

# Runs in a fresh interpreter: inside pytest our own autouse network guard patches sockets.
_PROBE = """
import socket
originals = (socket.getaddrinfo, socket.create_connection, socket.socket.connect,
             socket.socket.connect_ex)
import app.main, app.providers.factory, scripts.smoke_openai
current = (socket.getaddrinfo, socket.create_connection, socket.socket.connect,
           socket.socket.connect_ex)
assert current == originals, "socket functions were patched by an import"
import sys
assert not [m for m in sys.modules if m == "tests" or m.startswith("tests.")], "tests imported"
print("clean")
"""


def test_importing_app_and_scripts_leaves_sockets_untouched() -> None:
    result = subprocess.run(  # noqa: S603 — fixed interpreter and inline probe
        [sys.executable, "-c", _PROBE], cwd=BACKEND, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "clean"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_app_and_scripts_never_import_tests() -> None:
    offenders = [
        f"{path.relative_to(BACKEND)}: {module}"
        for folder in ("app", "scripts")
        for path in (BACKEND / folder).rglob("*.py")
        for module in _imported_modules(path)
        if module == "tests" or module.startswith("tests.")
    ]
    assert offenders == []
