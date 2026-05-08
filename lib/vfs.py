"""APEX VirtualFS — mount lógico read-only sobre el ecosistema cross-project.

Permite a un agente APEX en cualquier proyecto recorrer wiki/, decisiones,
handoffs, raw notes, errores y skills-history de los demás proyectos del
ecosistema con primitivas UNIX (`ls`, `cat`, `grep`, `find`) sin gastar
tokens en `apex_search_cross_project` repetidos.

Layout virtual (read-only):

    /projects/<slug>/wiki/                ← <root>/<slug>/wiki/
    /projects/<slug>/decisions/           ← <root>/<slug>/wiki/decisions/
    /projects/<slug>/handoffs/            ← <root>/<slug>/.apex/handoff/
    /projects/<slug>/raw/                 ← <root>/<slug>/.apex/raw/
    /projects/<slug>/errors/              ← virtual (context.db: errors)
    /projects/<slug>/skills-history/      ← virtual (role_invocations + verdicts)
    /lessons/critical/                    ← virtual (hub.db: cross_project_lessons)
    /lessons/by-project/<slug>.md         ← virtual (agregado por proyecto)
    /vault/                               ← <vault_root>/  (ApexVault)

Las categorías "reales" se mapean directamente a paths del filesystem
con whitelist en `vfs_allowed_roots` (lista de raíces permitidas, ej.
`~/RoadToDevOps`). Las "virtuales" se materializan on-demand en
`vfs_sql_render.py` y se cachean en `vfs_render_cache`.

S17.2 cubre exclusivamente el resolver + RBAC. Operaciones (ls, cat,
grep, find) se añaden en S17.3-S17.5.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal


# Categorías reales: prefijo virtual → segmentos relativos al directorio del proyecto
_PROJECT_REAL_MOUNTS: dict[str, tuple[str, ...]] = {
    "wiki": ("wiki",),
    "decisions": ("wiki", "decisions"),
    "handoffs": (".apex", "handoff"),
    "raw": (".apex", "raw"),
}

_PROJECT_VIRTUAL_MOUNTS: frozenset[str] = frozenset({
    "errors",
    "skills-history",
})

_LESSONS_MOUNTS: frozenset[str] = frozenset({
    "lessons-critical",
    "lessons-by-project",
})


class VFSPathError(ValueError):
    """Path virtual inválido o no autorizado."""


@dataclass(frozen=True)
class ResolvedPath:
    """Resultado de resolver un path virtual.

    `kind == "real"` significa que el path se mapea a un fichero/directorio
    bajo un `allowed_root`; `real_path` está poblado.

    `kind == "virtual"` significa que el path se materializa a partir de
    queries SQL (ver `vfs_sql_render.py`); `real_path is None`.
    """

    kind: Literal["real", "virtual"]
    category: str
    slug: str | None
    real_path: Path | None
    subpath: str
    is_root: bool


class VirtualFS:
    """Read-only mount lógico sobre proyectos APEX + ApexVault.

    Sin estado de sesión; cada `_resolve` valida desde cero. La whitelist
    de `allowed_roots` actúa como sandbox: cualquier path que tras
    normalizar se salga de un root permitido se rechaza.
    """

    def __init__(
        self,
        allowed_roots: Iterable[Path],
        vault_root: Path | None = None,
    ) -> None:
        self.allowed_roots: list[Path] = [Path(r).resolve() for r in allowed_roots]
        self.vault_root: Path | None = (
            Path(vault_root).resolve() if vault_root is not None else None
        )

    # --- public factory ----------------------------------------------------

    @classmethod
    def from_hub(cls, hub_db_path: Path | str) -> "VirtualFS":
        """Construye VirtualFS leyendo `vfs_allowed_roots` y `vfs_vault_root`
        de `hub.db.global_meta`. Best-effort: si la BD no existe o las claves
        no están, devuelve un VFS con whitelist vacía (cualquier resolve
        contra `/projects/...` falla con `unknown project`).
        """
        path = Path(hub_db_path)
        if not path.exists():
            return cls(allowed_roots=[], vault_root=None)
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            return cls(allowed_roots=[], vault_root=None)
        try:
            cur = conn.execute(
                "SELECT key, value FROM global_meta "
                "WHERE key IN ('vfs_allowed_roots', 'vfs_vault_root')"
            )
            roots: list[Path] = []
            vault: Path | None = None
            for key, value in cur.fetchall():
                if key == "vfs_allowed_roots":
                    try:
                        roots = [Path(p) for p in json.loads(value)]
                    except (TypeError, ValueError, json.JSONDecodeError):
                        roots = []
                elif key == "vfs_vault_root" and value:
                    vault = Path(value)
        except sqlite3.OperationalError:
            roots = []
            vault = None
        finally:
            conn.close()
        return cls(allowed_roots=roots, vault_root=vault)

    # --- core resolver -----------------------------------------------------

    def _resolve(self, virtual_path: str) -> ResolvedPath:
        """Mapea un path virtual a un `ResolvedPath` o lanza `VFSPathError`."""
        if not isinstance(virtual_path, str) or not virtual_path:
            raise VFSPathError("empty path")
        if not virtual_path.startswith("/"):
            raise VFSPathError("path must be absolute (start with '/')")
        if ".." in virtual_path.split("/"):
            raise VFSPathError("path traversal not allowed")

        parts = [p for p in virtual_path.split("/") if p]
        if not parts:
            raise VFSPathError("empty path")

        head = parts[0]
        if head == "projects":
            return self._resolve_project(parts[1:])
        if head == "vault":
            return self._resolve_vault(parts[1:])
        if head == "lessons":
            return self._resolve_lessons(parts[1:])
        raise VFSPathError(
            f"unknown mount '{head}': expected one of /projects, /vault, /lessons"
        )

    # --- branch: /projects/<slug>/<category>/... --------------------------

    def _resolve_project(self, parts: list[str]) -> ResolvedPath:
        if len(parts) < 1:
            raise VFSPathError("project slug missing")
        slug = parts[0]
        if not self._project_exists(slug):
            raise VFSPathError(f"unknown project '{slug}'")

        if len(parts) == 1:
            # `/projects/<slug>` — directorio raíz, tratamos como real
            for root in self.allowed_roots:
                candidate = root / slug
                if candidate.exists():
                    return ResolvedPath(
                        kind="real",
                        category="project-root",
                        slug=slug,
                        real_path=candidate,
                        subpath="",
                        is_root=True,
                    )

        category = parts[1]

        if category in _PROJECT_REAL_MOUNTS:
            return self._resolve_project_real(slug, category, parts[2:])
        if category in _PROJECT_VIRTUAL_MOUNTS:
            return self._resolve_project_virtual(slug, category, parts[2:])
        raise VFSPathError(
            f"unknown category '{category}' for project '{slug}'"
        )

    def _resolve_project_real(
        self, slug: str, category: str, rest: list[str]
    ) -> ResolvedPath:
        sub_segments = _PROJECT_REAL_MOUNTS[category]
        for root in self.allowed_roots:
            base = root / slug
            if not base.exists():
                continue
            real = base.joinpath(*sub_segments, *rest)
            try:
                resolved = real.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                raise VFSPathError(f"resolve error: {exc}") from exc
            # Sandbox: el path resuelto debe seguir bajo el root permitido.
            if not _is_under(resolved, root):
                raise VFSPathError("path traversal not allowed")
            return ResolvedPath(
                kind="real",
                category=category,
                slug=slug,
                real_path=resolved,
                subpath="/".join(rest),
                is_root=(len(rest) == 0),
            )
        raise VFSPathError(f"unknown project '{slug}'")

    def _resolve_project_virtual(
        self, slug: str, category: str, rest: list[str]
    ) -> ResolvedPath:
        return ResolvedPath(
            kind="virtual",
            category=category,
            slug=slug,
            real_path=None,
            subpath="/".join(rest),
            is_root=(len(rest) == 0),
        )

    # --- branch: /vault/... -----------------------------------------------

    def _resolve_vault(self, parts: list[str]) -> ResolvedPath:
        if self.vault_root is None:
            raise VFSPathError("vault not configured")
        real = self.vault_root.joinpath(*parts)
        try:
            resolved = real.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise VFSPathError(f"resolve error: {exc}") from exc
        if not _is_under(resolved, self.vault_root):
            raise VFSPathError("path traversal not allowed")
        return ResolvedPath(
            kind="real",
            category="vault",
            slug=None,
            real_path=resolved,
            subpath="/".join(parts),
            is_root=(len(parts) == 0),
        )

    # --- branch: /lessons/... ---------------------------------------------

    def _resolve_lessons(self, parts: list[str]) -> ResolvedPath:
        if not parts:
            raise VFSPathError("lessons subcategory missing")
        sub = parts[0]
        if sub == "critical":
            return ResolvedPath(
                kind="virtual",
                category="lessons-critical",
                slug=None,
                real_path=None,
                subpath="/".join(parts[1:]),
                is_root=(len(parts) == 1),
            )
        if sub == "by-project":
            slug = parts[1].removesuffix(".md") if len(parts) >= 2 else None
            return ResolvedPath(
                kind="virtual",
                category="lessons-by-project",
                slug=slug,
                real_path=None,
                subpath="/".join(parts[1:]),
                is_root=(len(parts) == 1),
            )
        raise VFSPathError(
            f"unknown lessons subcategory '{sub}': expected 'critical' or 'by-project'"
        )

    # --- helpers ----------------------------------------------------------

    def _project_exists(self, slug: str) -> bool:
        for root in self.allowed_roots:
            if (root / slug).exists() and (root / slug).is_dir():
                return True
        return False


def _is_under(path: Path, root: Path) -> bool:
    """True si `path` está bajo `root` (ambos resueltos)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
