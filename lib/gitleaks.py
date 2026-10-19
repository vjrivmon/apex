"""Ejecución de gitleaks (Sprint 19, Gap F).

gitleaks es un binario EXTERNO: no es una dependencia de Python y este módulo
no lo instala. Solo lo localiza, lo invoca y devuelve un resultado
estructurado.

FRONTERA DE RESPONSABILIDAD (importante)
-----------------------------------------
Este módulo EXECUTA gitleaks. NO decide si el proyecto tiene gitleaks
configurado: ese predicado vive en `lib/security_gate.py`
(`_check_gitleaks_configured(project_root)`, S19.1c), implementado en paralelo
por otro agente. Aquí `is_configured()` es solo una envoltura fina que
intenta reutilizar ese predicado y, si no está disponible, cae a una
comprobación local equivalente (`.husky/pre-commit` o `.gitleaks.toml`).
Esa duplicación es un fallback documentado, no la implementación principal:
si cambia el predicado de security_gate, este módulo lo hereda.

Uso:
    python -m lib.gitleaks --project-root .              # estado
    python -m lib.gitleaks --project-root . --staged      # ejecuta el escaneo
    python -m lib.gitleaks --project-root . --staged --timeout 30
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# Nombre del binario que se busca en el PATH.
GITLEAKS_BINARY = "gitleaks"

# Timeout por defecto (segundos) para la ejecución de gitleaks.
DEFAULT_TIMEOUT = 60.0

# Argumentos de la comprobación de lo staged. Es lo que ejecuta el hook
# pre-commit instalado por apex_scaffold_devops.
STAGED_ARGS = ("protect", "--staged", "--redact")


@dataclass
class GitleaksResult:
    """Resultado de una invocación de gitleaks.

    `ok` es True solo si gitleaks se ejecutó y devolvió 0. Si el binario no
    está, `available` es False y `ok` también: no se puede afirmar que no
    haya secretos si no se ha mirado.
    """

    ok: bool
    available: bool
    command: list[str]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None

    @property
    def summary(self) -> str:
        """Resumen de una línea, apto para logs y para el CLI."""
        if not self.available:
            return "gitleaks no disponible: no se ha escaneado nada"
        if self.timed_out:
            return f"gitleaks agotó el tiempo ({self.command[0]})"
        if self.ok:
            return "gitleaks: sin secretos en lo escaneado"
        return f"gitleaks: fallos (exit {self.returncode})"


def gitleaks_binary() -> str | None:
    """Ruta absoluta del binario gitleaks, o None si no está en el PATH."""
    return shutil.which(GITLEAKS_BINARY)


def is_available() -> bool:
    """True si el binario gitleaks está instalado y es ejecutable."""
    return gitleaks_binary() is not None


def run_gitleaks(cwd: Path | str, args: list[str] | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 binary: str | None = None) -> GitleaksResult:
    """Ejecuta gitleaks en `cwd` y devuelve el resultado.

    Seguridad: lista de argumentos (nunca `shell=True`), `cwd` explícito y
    timeout. `shell=True` permitiría que un argumento con metacaracteres
    ejecutase comandos arbitrarios; con lista, no hay intérprete.
    """
    exe = binary if binary is not None else gitleaks_binary()
    cmd = [exe or GITLEAKS_BINARY, *(args or [])]

    if exe is None:
        return GitleaksResult(
            ok=False,
            available=False,
            command=cmd,
            error=(
                "gitleaks no esta instalado. Instálalo con "
                "`brew install gitleaks`, `sudo apt install gitleaks` o "
                "`go install github.com/gitleaks/gitleaks/v8@latest`."
            ),
        )

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return GitleaksResult(
            ok=False,
            available=True,
            command=cmd,
            timed_out=True,
            stdout=_as_text(exc.stdout),
            stderr=_as_text(exc.stderr),
            error=f"gitleaks no ha terminado en {timeout}s",
        )
    except OSError as exc:
        return GitleaksResult(
            ok=False,
            available=True,
            command=cmd,
            error=f"no se ha podido ejecutar gitleaks: {exc}",
        )

    return GitleaksResult(
        ok=proc.returncode == 0,
        available=True,
        command=cmd,
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def protect_staged(cwd: Path | str, timeout: float = DEFAULT_TIMEOUT) -> GitleaksResult:
    """Ejecuta `gitleaks protect --staged --redact` en `cwd`."""
    return run_gitleaks(cwd, args=list(STAGED_ARGS), timeout=timeout)


def _as_text(value: object) -> str:
    """Normaliza la salida de TimeoutExpired (bytes o str) a texto."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _security_gate_predicate():
    """Devuelve `_check_gitleaks_configured` de security_gate, o None.

    El predicado de verdad vive en security_gate (S19.1c). Si ese módulo no
    está importable, quien llama usa el fallback local.
    """
    try:
        from security_gate import _check_gitleaks_configured  # type: ignore
    except Exception:
        try:
            from lib.security_gate import _check_gitleaks_configured  # type: ignore
        except Exception:
            return None
    return _check_gitleaks_configured


def _local_configured(project_root: Path) -> bool:
    """Fallback local: hay hook de gitleaks o fichero de configuración."""
    return (project_root / ".husky" / "pre-commit").exists() or \
        (project_root / ".gitleaks.toml").exists()


def is_configured(project_root: Path | str) -> bool:
    """True si el proyecto tiene gitleaks configurado.

    Envoltura fina sobre el predicado de `lib/security_gate.py`. Si ese
    predicado no está disponible, cae a la comprobación local equivalente.
    """
    root = Path(project_root)
    predicate = _security_gate_predicate()
    if predicate is not None:
        return bool(predicate(root))
    return _local_configured(root)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project-root", type=Path, default=Path("."),
                   help="Directorio del proyecto (raíz del repo)")
    p.add_argument("--staged", action="store_true",
                   help="Ejecuta `gitleaks protect --staged --redact`")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                   help=f"Timeout en segundos (default {DEFAULT_TIMEOUT:g})")
    args = p.parse_args(argv)

    root = args.project_root.resolve()
    binary = gitleaks_binary()
    print(f"gitleaks: {binary or 'NO INSTALADO'}")
    print(f"configurado en el proyecto: {is_configured(root)}")

    if not args.staged:
        return 0 if binary else 1

    result = protect_staged(root, timeout=args.timeout)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    print(result.summary)
    if result.error:
        print(result.error, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
