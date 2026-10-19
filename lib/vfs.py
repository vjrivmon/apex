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

Solo-lectura: no existe ninguna operación de escritura. `write()` (y
cualquier intento de mutación) devuelve EROFS, patrón Mintlify.

S17.2 cubre exclusivamente el resolver + RBAC. Operaciones (ls, cat,
grep, find) se añaden en S17.3-S17.5. S17.6 añade la materialización
SQL→markdown de las categorías virtuales.
"""
from __future__ import annotations

import fnmatch
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

# Categorías que un proyecto expone en su raíz. `ls /projects/<slug>`
# devuelve este índice en vez del contenido del directorio del proyecto:
# así el VFS no filtra el código fuente ni el .git de los proyectos.
_PROJECT_CATEGORIES: tuple[str, ...] = (
    "wiki",
    "decisions",
    "handoffs",
    "raw",
    "errors",
    "skills-history",
)

# Mensaje canónico de escritura rechazada (patrón Mintlify, blueprint §3).
EROFS_MESSAGE = "EROFS: read-only file system"

#: Flags de grep soportados por el VirtualFS (blueprint S17 §3).
GREP_FLAG_CHARS = frozenset("i r n l E")

#: Comandos admitidos por el exec del VirtualFS. Todo lo demás se rechaza.
ALLOWED_EXEC_COMMANDS: tuple[str, ...] = ("ls", "cat", "grep", "find")

#: Comandos de escritura: se rechazan con EROFS explícito.
WRITE_EXEC_COMMANDS: frozenset[str] = frozenset({
    "rm", "rmdir", "mv", "cp", "touch", "mkdir", "echo", "tee", "dd",
    "chmod", "chown", "ln", "truncate", "shred", "install", "sed",
})

#: Caracteres prohibidos en una línea de exec. `|` es el separador de
#: pipes y se valida aparte; el resto son puertas de inyección.
FORBIDDEN_EXEC_CHARS: frozenset[str] = frozenset(";&$`><(){}\\")


def global_memory_dir() -> Path:
    """`~/.apex` — la memoria global cross-project de APEX.

    NO es un proyecto: es memoria append-only de errores graves. Nunca
    debe ser alcanzable a través del VirtualFS.
    """
    return Path.home() / ".apex"


class VFSError(Exception):
    """Error genérico del VirtualFS (file not found, not a directory, etc.).

    `VFSPathError` (path inválido / RBAC) es subclase para mantener el
    contrato existente; código que ya capturaba `VFSPathError` sigue
    funcionando.
    """


class VFSPathError(VFSError, ValueError):
    """Path virtual inválido o no autorizado."""


class VFSWriteError(VFSError):
    """Escritura rechazada: el VirtualFS es read-only (EROFS)."""


class VFSExecError(VFSError):
    """Comando del exec rechazado por la whitelist (no es un error de FS)."""


class VFSNotImplementedError(VFSError):
    """Operación sobre categoría virtual aún no implementada (S17.6)."""


@dataclass(frozen=True)
class VFSEntry:
    """Entry en una listing virtual. Equivalente a una línea de `ls -l`."""

    name: str
    kind: Literal["file", "dir"]
    size_bytes: int


@dataclass(frozen=True)
class ResolvedPath:
    """Resultado de resolver un path virtual.

    `kind == "real"` significa que el path se mapea a un fichero/directorio
    bajo un `allowed_root`; `real_path` está poblado.

    `kind == "virtual"` significa que el path se materializa a partir de
    queries SQL (ver `vfs_sql_render.py`); `real_path is None`.

    `kind == "collection"` significa que el path no mapea a un único
    fichero real sino a un conjunto (raíz del filesystem virtual o raíz
    de proyectos); `real_path is None`.
    """

    kind: Literal["real", "virtual", "collection"]
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

    `materializer` es opcional. Cuando se pasa (lo hace el servidor MCP
    con `vfs_sql_render.SqlMaterializer`), las categorías virtuales
    (`errors`, `skills-history`, `lessons-*`) se materializan a markdown
    en lugar de lanzar `VFSNotImplementedError`. El materializer es
    duck-typed: debe exponer `stat`, `list_dir`, `read_file` y
    `list_files` (ver `vfs_sql_render.SqlMaterializer`).
    """

    def __init__(
        self,
        allowed_roots: Iterable[Path],
        vault_root: Path | None = None,
        materializer: object | None = None,
    ) -> None:
        self.allowed_roots: list[Path] = [
            Path(r).resolve() for r in allowed_roots
        ]
        self.vault_root: Path | None = (
            Path(vault_root).resolve() if vault_root is not None else None
        )
        self.materializer = materializer
        self._assert_not_global_memory(self.allowed_roots, "allowed_root")
        if self.vault_root is not None:
            self._assert_not_global_memory([self.vault_root], "vault_root")

    @staticmethod
    def _assert_not_global_memory(roots: list[Path], label: str) -> None:
        """`~/.apex` es la memoria global, nunca un proyecto alcanzable.

        Se falla en voz alta en vez de filtrar en silencio: una whitelist
        mal configurada es un fallo de configuración, no algo que se
        deba tolerar callando.
        """
        memoria = global_memory_dir()
        for root in roots:
            if root == memoria or _is_under(root, memoria):
                raise VFSPathError(
                    f"{label} no permitido: {root} está dentro de la memoria "
                    f"global {memoria}, que no es un proyecto"
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

    @classmethod
    def from_hub_with_defaults(
        cls,
        hub_db_path: Path | str,
        default_roots: Iterable[Path],
        default_vault: Path | None = None,
    ) -> "VirtualFS":
        """Como `from_hub`, pero con whitelist por defecto.

        `hub.db.global_meta.vfs_allowed_roots` manda; si la clave falta o
        está vacía se usan `default_roots` (por defecto `~/RoadToDevOps`) y
        `default_vault` (por defecto la ruta del ApexVault).
        """
        vfs = cls.from_hub(hub_db_path)
        if not vfs.allowed_roots:
            vfs = cls(
                allowed_roots=[Path(r) for r in default_roots],
                vault_root=default_vault,
            )
        elif vfs.vault_root is None and default_vault is not None:
            vfs = cls(
                allowed_roots=vfs.allowed_roots,
                vault_root=default_vault,
            )
        return vfs

    # --- public operations -------------------------------------------------

    def ls(self, virtual_path: str) -> list[VFSEntry]:
        """Lista entries de un directorio virtual. Read-only.

        Devuelve entries ordenados por nombre. Lanza `VFSPathError` para
        paths inválidos / RBAC, `VFSError("not found"|"not a directory")`
        para errores de filesystem, `VFSNotImplementedError` para
        categorías virtuales (errors, skills-history, lessons-*) cuando no
        hay materializer conectado.
        """
        resolved = self._resolve(virtual_path)
        if resolved.kind == "virtual":
            return self._materialize_ls(resolved)
        if resolved.kind == "collection":
            if resolved.category == "root":
                return self.ls_root()
            return self._list_projects()
        path = resolved.real_path
        assert path is not None  # kind=real implica real_path != None
        if not path.exists():
            raise VFSError(f"not found: {virtual_path}")
        if not path.is_dir():
            raise VFSError(f"not a directory: {virtual_path}")
        if resolved.category == "project-root":
            # Índice de categorías del proyecto: no se filtra el código.
            return [
                VFSEntry(name=cat, kind="dir", size_bytes=0)
                for cat in _PROJECT_CATEGORIES
            ]
        entries: list[VFSEntry] = []
        for child in sorted(path.iterdir(), key=lambda p: p.name):
            try:
                size = child.stat().st_size if child.is_file() else 0
            except OSError:
                size = 0
            entries.append(
                VFSEntry(
                    name=child.name,
                    kind="dir" if child.is_dir() else "file",
                    size_bytes=size,
                )
            )
        return entries

    def ls_root(self) -> list[VFSEntry]:
        """Entries del raíz del filesystem virtual (`/`).

        Montajes disponibles: `/projects`, `/lessons` y `/vault` (si hay
        vault configurado).
        """
        entries = [
            VFSEntry(name="projects", kind="dir", size_bytes=0),
            VFSEntry(name="lessons", kind="dir", size_bytes=0),
        ]
        if self.vault_root is not None:
            entries.append(VFSEntry(name="vault", kind="dir", size_bytes=0))
        return entries

    def find(
        self, virtual_path: str, name: str | None = None
    ) -> list[str]:
        """Lista recursivamente los archivos bajo `virtual_path`, opcionalmente
        filtrados por glob `name` (estilo `find ... -name <pattern>`).

        Devuelve **paths virtuales** (no reales del filesystem). Si
        `virtual_path` apunta a un archivo, devuelve sólo ese path si
        matchea el pattern (o el archivo entero si `name is None`).
        """
        resolved = self._resolve(virtual_path)
        if resolved.kind == "virtual":
            return self._materialize_find(resolved)
        if resolved.kind == "collection":
            if resolved.category == "root":
                return self._find_everything(name)
            return self._find_all_projects(name)
        path = resolved.real_path
        assert path is not None
        if not path.exists():
            raise VFSError(f"not found: {virtual_path}")

        if resolved.category == "project-root":
            return self._find_project_files(resolved.slug, name)

        mount_real_root, mount_virtual_prefix = self._mount_for(resolved)
        pattern = name or "*"

        if path.is_file():
            if fnmatch.fnmatch(path.name, pattern):
                return [self._real_to_virtual(path, mount_real_root, mount_virtual_prefix)]
            return []

        matches: list[str] = []
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            if name is not None and not fnmatch.fnmatch(child.name, pattern):
                continue
            matches.append(
                self._real_to_virtual(child, mount_real_root, mount_virtual_prefix)
            )
        return sorted(matches)

    def cat(self, virtual_path: str) -> str:
        """Lee el contenido de un archivo virtual como texto UTF-8.

        Lanza `VFSError` para paths que no son archivos o no existen, y
        `VFSNotImplementedError` para virtuales sin materializer.
        """
        resolved = self._resolve(virtual_path)
        if resolved.kind == "virtual":
            return self._materialize_cat(resolved)
        if resolved.kind == "collection":
            raise VFSError(f"is a directory: {virtual_path}")
        path = resolved.real_path
        assert path is not None
        if not path.exists():
            raise VFSError(f"not found: {virtual_path}")
        if path.is_dir():
            raise VFSError(f"is a directory: {virtual_path}")
        if resolved.category == "project-root":
            raise VFSError(f"is a directory: {virtual_path}")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise VFSError(f"binary file (not utf-8): {virtual_path}") from exc

    def write(self, virtual_path: str, content: str = "") -> None:
        """Siempre falla con EROFS: el VirtualFS es read-only.

        Existe para que el intento de escritura tenga un error explícito y
        uniforme (patrón Mintlify) en vez de un AttributeError.
        """
        raise VFSWriteError(f"{EROFS_MESSAGE}: {virtual_path}")

    # --- catálogo de proyectos ---------------------------------------------

    def project_slugs(self) -> list[str]:
        """Slugs de los proyectos alcanzables (directorios bajo las raíces
        permitidas). Ordenados y sin duplicados."""
        slugs: set[str] = set()
        for root in self.allowed_roots:
            try:
                children = list(root.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir() or child.name.startswith("."):
                    continue
                slugs.add(child.name)
        return sorted(slugs)

    def project_db_path(self, slug: str) -> Path | None:
        """`context.db` del proyecto `slug`, o None si no lo tiene."""
        for root in self.allowed_roots:
            candidate = root / slug / ".apex" / "context.db"
            if candidate.exists():
                return candidate
        return None

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
            # "/" es la raíz del filesystem virtual: colección de montajes.
            return ResolvedPath(
                kind="collection",
                category="root",
                slug=None,
                real_path=None,
                subpath="",
                is_root=True,
            )

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
            # "/projects" — colección de todos los proyectos alcanzables.
            return ResolvedPath(
                kind="collection",
                category="projects-root",
                slug=None,
                real_path=None,
                subpath="",
                is_root=True,
            )
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
            # La memoria global (~/.apex) no es un proyecto alcanzable.
            if _is_global_memory(resolved):
                raise VFSPathError(
                    f"path not allowed: {resolved} is inside the global memory"
                )
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
            candidate = root / slug
            if not candidate.exists() or not candidate.is_dir():
                continue
            if _is_global_memory(candidate.resolve(strict=False)):
                continue
            return True
        return False

    def _mount_for(self, resolved: ResolvedPath) -> tuple[Path, str]:
        """Devuelve (mount_real_root, mount_virtual_prefix) para un ResolvedPath
        de tipo `real`. Necesario para reverse-mapping en `find`."""
        if resolved.category == "vault":
            assert self.vault_root is not None
            return self.vault_root, "/vault"
        if resolved.category in _PROJECT_REAL_MOUNTS:
            slug = resolved.slug
            assert slug is not None
            for root in self.allowed_roots:
                base = root / slug
                if base.exists():
                    mount_root = base.joinpath(*_PROJECT_REAL_MOUNTS[resolved.category])
                    return mount_root, f"/projects/{slug}/{resolved.category}"
        raise VFSError(f"no mount for category '{resolved.category}'")

    @staticmethod
    def _real_to_virtual(real: Path, mount_root: Path, mount_prefix: str) -> str:
        """Construye el path virtual a partir de un path real bajo un mount."""
        rel = real.relative_to(mount_root).as_posix()
        if rel == ".":
            return mount_prefix
        return f"{mount_prefix}/{rel}"

    # --- materialización de categorías virtuales --------------------------

    def _materialize_ls(self, resolved: ResolvedPath) -> list[VFSEntry]:
        if self.materializer is None:
            raise VFSNotImplementedError(
                f"ls on virtual category '{resolved.category}' not yet implemented "
                "(scheduled for S17.6)"
            )
        entries = self.materializer.list_dir(resolved)
        return [
            VFSEntry(
                name=str(entry["name"]),
                kind="dir" if entry.get("kind") == "dir" else "file",
                size_bytes=int(entry.get("size_bytes", 0)),
            )
            for entry in entries
        ]

    def _materialize_cat(self, resolved: ResolvedPath) -> str:
        if self.materializer is None:
            raise VFSNotImplementedError(
                f"cat on virtual category '{resolved.category}' not yet implemented "
                "(scheduled for S17.6)"
            )
        stat = self.materializer.stat(resolved)
        if stat is None:
            raise VFSError(f"not found: {resolved.subpath or resolved.category}")
        if stat.get("kind") == "dir":
            raise VFSError(f"is a directory: {resolved.subpath or resolved.category}")
        return self.materializer.read_file(resolved)

    def _materialize_find(self, resolved: ResolvedPath) -> list[str]:
        if self.materializer is None:
            raise VFSNotImplementedError(
                f"find on virtual category '{resolved.category}' not yet implemented "
                "(scheduled for S17.6)"
            )
        return list(self.materializer.list_files(resolved))

    # --- colecciones -------------------------------------------------------

    def _list_projects(self) -> list[VFSEntry]:
        """Entries de `/projects`: un directorio por proyecto alcanzable."""
        return [
            VFSEntry(name=slug, kind="dir", size_bytes=0)
            for slug in self.project_slugs()
        ]

    def _find_project_files(self, slug: str | None, name: str | None) -> list[str]:
        """Archivos de las categorías REALES de un proyecto.

        No se recorre el directorio del proyecto entero: el VFS solo
        expone wiki, decisions, handoffs y raw.
        """
        if not slug:
            return []
        found: list[str] = []
        for category in _PROJECT_REAL_MOUNTS:
            try:
                found.extend(self.find(f"/projects/{slug}/{category}", name))
            except VFSError:
                continue
        return sorted(found)

    def _find_all_projects(self, name: str | None) -> list[str]:
        """Archivos de todos los proyectos alcanzables (grep -r cross-project)."""
        found: list[str] = []
        for slug in self.project_slugs():
            found.extend(self._find_project_files(slug, name))
        return sorted(found)

    def _find_everything(self, name: str | None) -> list[str]:
        """Archivos de todos los montajes: proyectos y vault."""
        found = list(self._find_all_projects(name))
        if self.vault_root is not None and self.vault_root.exists():
            try:
                found.extend(self.find("/vault", name))
            except VFSError:
                pass
        return sorted(found)


def _is_under(path: Path, root: Path) -> bool:
    """True si `path` está bajo `root` (ambos resueltos)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_global_memory(path: Path) -> bool:
    """True si `path` es la memoria global (`~/.apex`) o está dentro de ella."""
    memoria = global_memory_dir()
    return path == memoria or _is_under(path, memoria)


# ═══════════════════════════════════════════════════════════════════════
# Exec — una línea tipo bash limitada al VirtualFS
#
# Riesgo R3 del blueprint: un parser de comandos mal hecho es un agujero
# de inyección. Aquí no hay `subprocess`: el comando se parsea con un
# parser explícito y una whitelist. Lo único que se ejecuta son las
# primitivas del VFS sobre paths virtuales, que a su vez pasan por el
# resolver con su sandbox.
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ExecFilter:
    """Filtro de pipe permitido: `grep`, `head` o `wc -l`."""

    kind: str  # "grep" | "head" | "wc"
    pattern: str | None = None
    flags: str = ""
    count: int = 10


@dataclass(frozen=True)
class ExecPlan:
    """Comando del exec ya parseado y validado."""

    name: str  # ls | cat | grep | find
    path: str | None = None
    pattern: str | None = None
    flags: str = ""
    name_pattern: str | None = None
    filters: tuple[ExecFilter, ...] = ()


@dataclass(frozen=True)
class ExecResult:
    """Salida del exec: stdout, stderr y código de salida."""

    stdout: str
    stderr: str
    exit_code: int
    warnings: tuple[str, ...] = ()


def _shlex_split(segment: str) -> list[str]:
    """Divide un segmento en tokens. Error explícito si las comillas no
    cierran (un `shlex` silencioso sería un agujero)."""
    import shlex

    try:
        return shlex.split(segment)
    except ValueError as exc:
        raise VFSExecError(f"comando mal formado: {exc}") from exc


def _check_exec_path(path: str) -> str:
    """Valida un path virtual de los argumentos del exec."""
    if not path.startswith("/"):
        raise VFSExecError(
            f"path virtual debe ser absoluto (empezar por '/'): {path!r}"
        )
    if ".." in path.split("/"):
        raise VFSExecError(f"path traversal not allowed: {path!r}")
    return path


def _split_exec_flags(
    args: list[str], allowed: frozenset[str]
) -> tuple[str, list[str]]:
    """Separa los flags iniciales del resto de argumentos."""
    flags = ""
    rest: list[str] = []
    for token in args:
        if token.startswith("-") and token != "-":
            chars = token[1:]
            for char in chars:
                if char not in allowed:
                    raise VFSExecError(f"flag no permitido: -{char}")
            flags += chars
        else:
            rest.append(token)
    return flags, rest


def _parse_exec_filter(segment: str) -> ExecFilter:
    """Parsea un sufijo de pipe. Solo `grep`, `head` y `wc -l`."""
    tokens = _shlex_split(segment)
    if not tokens:
        raise VFSExecError("filtro de pipe vacío")
    kind = tokens[0]
    if kind == "grep":
        flags, rest = _split_exec_flags(tokens[1:], GREP_FLAG_CHARS)
        if len(rest) != 1:
            raise VFSExecError(
                "el filtro grep necesita exactamente un patrón"
            )
        return ExecFilter(kind="grep", pattern=rest[0], flags=flags)
    if kind == "head":
        rest = tokens[1:]
        count = 10
        if rest:
            if len(rest) == 2 and rest[0] == "-n":
                try:
                    count = int(rest[1])
                except ValueError as exc:
                    raise VFSExecError(
                        f"head -n necesita un número: {rest[1]!r}"
                    ) from exc
                if count < 0:
                    raise VFSExecError("head -n necesita un número >= 0")
            else:
                raise VFSExecError("el filtro head solo admite '-n <N>'")
        return ExecFilter(kind="head", count=count)
    if kind == "wc":
        if len(tokens) != 2 or tokens[1] != "-l":
            raise VFSExecError("el filtro wc solo admite '-l'")
        return ExecFilter(kind="wc")
    raise VFSExecError(
        f"filtro no permitido: {kind!r} (permitidos: grep, head, wc -l)"
    )


def parse_exec_command(command: str) -> ExecPlan:
    """Parsea una línea tipo bash y devuelve el plan de ejecución.

    Lanza `VFSExecError` si algo no está en la whitelist. No se ejecuta
    nada aquí: el parseo y la ejecución están separados para que el
    rechazo sea testeable sin tocar el filesystem.
    """
    if not isinstance(command, str):
        raise VFSExecError("el comando debe ser una string")
    text = command.strip()
    if not text:
        raise VFSExecError("comando vacío")
    for char in text:
        if char in FORBIDDEN_EXEC_CHARS:
            raise VFSExecError(
                f"carácter no permitido en el comando: {char!r}"
            )
        if char in "\n\r":
            raise VFSExecError("el comando debe ser una sola línea")

    segments = text.split("|")
    if any(not segment.strip() for segment in segments):
        raise VFSExecError("pipe vacío: falta un comando antes o después de '|'")

    tokens = _shlex_split(segments[0])
    if not tokens:
        raise VFSExecError("comando vacío")
    name = tokens[0]
    if name not in ALLOWED_EXEC_COMMANDS:
        raise VFSExecError(
            f"comando no permitido: {name!r} "
            f"(permitidos: {', '.join(ALLOWED_EXEC_COMMANDS)})"
        )
    args = tokens[1:]

    if name == "ls":
        if len(args) > 1:
            raise VFSExecError("ls admite como mucho un path")
        path = _check_exec_path(args[0]) if args else None
        plan = ExecPlan(name="ls", path=path)
    elif name == "cat":
        if len(args) != 1:
            raise VFSExecError("cat necesita exactamente un path")
        plan = ExecPlan(name="cat", path=_check_exec_path(args[0]))
    elif name == "grep":
        flags, rest = _split_exec_flags(args, GREP_FLAG_CHARS)
        if len(rest) != 2:
            raise VFSExecError(
                "grep necesita <patrón> y <path> (flags: -i -r -n -l -E)"
            )
        plan = ExecPlan(
            name="grep",
            path=_check_exec_path(rest[1]),
            pattern=rest[0],
            flags=flags,
        )
    elif name == "find":
        if not args:
            raise VFSExecError("find necesita un path")
        path = _check_exec_path(args[0])
        rest = args[1:]
        name_pattern = None
        if rest:
            if len(rest) != 2 or rest[0] != "-name":
                raise VFSExecError("find solo admite el sufijo '-name <patrón>'")
            name_pattern = rest[1]
        plan = ExecPlan(name="find", path=path, name_pattern=name_pattern)
    else:  # pragma: no cover — la whitelist lo impide
        raise VFSExecError(f"comando no permitido: {name!r}")

    filters = tuple(_parse_exec_filter(segment) for segment in segments[1:])
    return ExecPlan(
        name=plan.name,
        path=plan.path,
        pattern=plan.pattern,
        flags=plan.flags,
        name_pattern=plan.name_pattern,
        filters=filters,
    )


def _exec_base(vfs: VirtualFS, plan: ExecPlan) -> tuple[str, int, tuple[str, ...]]:
    """Ejecuta el comando base. Devuelve (stdout, exit_code, avisos)."""
    if plan.name == "ls":
        entries = vfs.ls(plan.path) if plan.path else vfs.ls_root()
        lines = [f"{e.name}/" if e.kind == "dir" else e.name for e in entries]
        return ("\n".join(lines) + "\n" if lines else ""), 0, ()
    if plan.name == "cat":
        assert plan.path is not None
        return vfs.cat(plan.path), 0, ()
    if plan.name == "grep":
        assert plan.path is not None and plan.pattern is not None
        # Import perezoso: `vfs_grep` importa de `vfs`, así que importarlo
        # arriba del todo sería un ciclo.
        from vfs_grep import grep_detailed

        outcome = grep_detailed(
            vfs,
            plan.pattern,
            plan.path,
            f"-{plan.flags}" if plan.flags else "",
            use_fts_prefilter=True,
        )
        lines = []
        for hit in outcome.hits:
            if "l" in plan.flags:
                lines.append(hit.virtual_path)
            elif "n" in plan.flags:
                lines.append(f"{hit.virtual_path}:{hit.line_num}:{hit.line}")
            else:
                lines.append(f"{hit.virtual_path}:{hit.line}")
        stdout = "\n".join(lines) + ("\n" if lines else "")
        return stdout, (0 if outcome.hits else 1), outcome.warnings
    if plan.name == "find":
        assert plan.path is not None
        paths = vfs.find(plan.path, plan.name_pattern)
        stdout = "\n".join(paths) + ("\n" if paths else "")
        return stdout, 0, ()
    raise VFSExecError(f"comando no permitido: {plan.name!r}")  # pragma: no cover


def _apply_exec_filter(filtro: ExecFilter, stdout: str) -> str:
    """Aplica un filtro de pipe a la salida anterior."""
    lines = stdout.splitlines()
    if filtro.kind == "grep":
        import re

        re_flags = re.IGNORECASE if "i" in filtro.flags else 0
        try:
            regex = re.compile(filtro.pattern or "", re_flags)
        except re.error as exc:
            raise VFSExecError(f"patrón inválido: {exc}") from exc
        out = []
        for i, line in enumerate(lines, 1):
            if not regex.search(line):
                continue
            if "n" in filtro.flags:
                out.append(f"{i}:{line}")
            else:
                out.append(line)
        return "\n".join(out) + ("\n" if out else "")
    if filtro.kind == "head":
        kept = lines[: filtro.count]
        return "\n".join(kept) + ("\n" if kept else "")
    if filtro.kind == "wc":
        return f"{len(lines)}\n"
    raise VFSExecError(f"filtro no permitido: {filtro.kind!r}")  # pragma: no cover


def run_exec(vfs: VirtualFS, command: str) -> ExecResult:
    """Ejecuta una línea tipo bash limitada sobre el VirtualFS.

    Nunca lanza por un comando inválido: devuelve el error en `stderr`
    con `exit_code` 2 (comando rechazado) o 1 (error de filesystem).
    """
    try:
        plan = parse_exec_command(command)
    except VFSExecError as exc:
        first = command.strip().split()[0] if command.strip() else ""
        if first in WRITE_EXEC_COMMANDS:
            return ExecResult(
                stdout="",
                stderr=f"{EROFS_MESSAGE} — comando de escritura no permitido: {first!r}",
                exit_code=2,
            )
        return ExecResult(stdout="", stderr=str(exc), exit_code=2)

    try:
        stdout, exit_code, warnings = _exec_base(vfs, plan)
    except VFSError as exc:
        return ExecResult(stdout="", stderr=str(exc), exit_code=1)
    except ValueError as exc:
        return ExecResult(stdout="", stderr=str(exc), exit_code=1)

    for filtro in plan.filters:
        try:
            stdout = _apply_exec_filter(filtro, stdout)
        except VFSExecError as exc:
            return ExecResult(stdout="", stderr=str(exc), exit_code=2)
    return ExecResult(
        stdout=stdout, stderr="", exit_code=exit_code, warnings=warnings
    )

