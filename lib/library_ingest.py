"""Library Ingest — Sprint 11.3.

Descubre e ingiere skills externas desde:

- **GitHub** (fuente principal): repos populares con `claude-skills` en topic
  o nombre, awesome-lists curadas. Consulta GitHub Search API + Tree API.
- **library-skills CLI** (fuente complementaria): wrapper sobre
  `uvx library-skills` cuando el proyecto APEX usa Python/JS y tiene
  `pyproject.toml` o `package.json`.

Pipeline: fetch → validate (frontmatter + longitud + secretos) → propose. Las
propuestas se escriben en `.apex/skill-proposals/import-<slug>.md` reusando
el flujo de `skill_forge.approve/reject` (mismo dir, mismo formato).

Diseño:

- HTTP via stdlib `urllib.request` para no añadir deps. Timeout 10s wall-clock.
- GitHub API requests pueden ir sin token (rate limit 60/h por IP); con token
  via `GITHUB_TOKEN` env var sube a 5000/h.
- Cache via tabla `library_imports` (Sprint 11.3 schema migration en
  `lib/context_db.py`). No re-descarga el mismo SHA dos veces.
- Validación BLOQUEA antes de escribir proposal: si falla, se descarta y se
  acumula el motivo en `IngestResult.invalid` (no se escribe ruido a disco).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

# ── Constantes ────────────────────────────────────────────────────────────

GH_API_BASE = "https://api.github.com"
GH_RAW_BASE = "https://raw.githubusercontent.com"

# Búsqueda de repos: por orden de prioridad. Sólo `in:name` para evitar
# falsos positivos en topics ruidosos.
GH_DEFAULT_QUERIES = (
    "awesome-claude-skills in:name",
    "claude-skills in:name",
    "topic:claude-skills",
)

GH_MIN_STARS = 50
GH_DEFAULT_LIMIT_REPOS = 8
GH_MAX_SKILLS_PER_REPO = 30
HTTP_TIMEOUT_S = 10.0
SUBPROCESS_TIMEOUT_S = 30.0

MAX_DESCRIPTION_LEN = 200
MAX_BODY_BYTES = 50 * 1024  # 50KB
MIN_BODY_BYTES = 100
MAX_NAME_LEN = 60

# Patrones de secretos: si match → descartar la skill.
_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"sk_(live|test)_[0-9a-zA-Z]{24,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class SkillRef:
    """Referencia a una skill descubierta antes de ser propuesta."""

    name: str
    description: str
    source: str               # "github" | "pkg"
    source_url: str           # URL canónica (gh blob URL o npm/pypi)
    sha: str                  # commit/blob SHA (gh) o version/lib (pkg)
    raw_md: str               # contenido completo del SKILL.md
    kind: str = "library"     # "library" | "awesome"
    extra: dict[str, Any] = field(default_factory=dict)

    def slug(self) -> str:
        h = hashlib.sha1(
            f"{self.source}:{self.source_url}:{self.sha}".encode("utf-8")
        ).hexdigest()[:8]
        norm = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")[:40]
        if not norm:
            norm = "skill"
        return f"import-{self.source}-{norm}-{h}"


@dataclass
class LibraryProposal:
    """Propuesta lista para escribir a `.apex/skill-proposals/`.

    Usa delimitador de 4 backticks alrededor del bloque ```markdown porque
    los SKILL.md descargados suelen contener bloques de código triple-backtick
    propios. `skill_forge._extract_skill_block` busca primero 4 backticks y
    luego cae a 3 (compat con proposals del Sprint 11.2).
    """

    ref: SkillRef
    issues: list[str] = field(default_factory=list)  # warnings no bloqueantes

    @property
    def slug(self) -> str:
        return self.ref.slug()

    def to_markdown(self) -> str:
        ev = {
            "source": self.ref.source,
            "source_url": self.ref.source_url,
            "sha": self.ref.sha,
            "kind": self.ref.kind,
        }
        if self.ref.extra:
            ev.update(self.ref.extra)
        ev_json = json.dumps(ev, indent=2, ensure_ascii=False)
        warns = ""
        if self.issues:
            warns = (
                "## Avisos no bloqueantes\n\n"
                + "\n".join(f"- {w}" for w in self.issues)
                + "\n\n"
            )
        return (
            f"# Library Ingest Proposal — {self.ref.name}\n\n"
            f"- **Slug**: `{self.slug}`\n"
            f"- **Detector**: `library_import`\n"
            f"- **Fuente**: {self.ref.source} · {self.ref.source_url}\n\n"
            f"## Descripción\n\n{self.ref.description}\n\n"
            f"## Evidencia\n\n```json\n{ev_json}\n```\n\n"
            f"{warns}"
            f"## Draft de SKILL.md\n\n"
            f"````markdown\n{self.ref.raw_md.rstrip()}\n````\n\n"
            f"## Aprobar\n\n"
            f"`apex_skill_forge_approve(\"{self.slug}\")` mueve la skill a "
            f"`~/.claude/skills/{self.slug}/SKILL.md` y borra esta propuesta.\n\n"
            f"## Rechazar\n\n"
            f"`apex_skill_forge_reject(\"{self.slug}\", \"motivo\")` registra "
            f"el rechazo y borra esta propuesta. La misma skill no se "
            f"volverá a proponer aunque se vuelva a ingerir.\n"
        )


@dataclass
class IngestResult:
    """Resumen de un pase de ingest. Apto para serializar a la respuesta MCP."""

    written: list[str] = field(default_factory=list)
    already_proposed: list[str] = field(default_factory=list)
    already_imported: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    invalid: list[tuple[str, str]] = field(default_factory=list)  # (slug, motivos)
    repos_searched: int = 0
    sources_used: list[str] = field(default_factory=list)


# ── HTTP helpers (stdlib) ────────────────────────────────────────────────

def _gh_headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "apex-library-ingest/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _http_get_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_S,
) -> dict | list:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8", errors="replace"))


def _http_get_text(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_S,
    max_bytes: int = MAX_BODY_BYTES + 1024,
) -> str:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Response too large (>{max_bytes} bytes): {url}")
    return data.decode("utf-8", errors="replace")


# ── Validación ────────────────────────────────────────────────────────────

def parse_frontmatter(md: str) -> dict[str, str] | None:
    m = _FRONTMATTER_RE.search(md)
    if not m:
        return None
    block = m.group(1)
    out: dict[str, str] = {}
    current_key: str | None = None
    for line in block.splitlines():
        # Continuación de valor multilínea (indentado).
        if line.startswith((" ", "\t")) and current_key is not None:
            out[current_key] += " " + line.strip()
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            key = k.strip()
            if not key:
                continue
            out[key] = v.strip()
            current_key = key
    return out


def validate_skill(ref: SkillRef) -> tuple[bool, list[str]]:
    """Filtro determinista. (valid, issues). Si valid==False, NO se propone."""
    fm = parse_frontmatter(ref.raw_md)
    if fm is None:
        return False, ["sin frontmatter YAML al inicio (debe empezar con "
                       "`---\\nname: ...\\ndescription: ...\\n---`)"]
    if not fm.get("name"):
        return False, ["frontmatter sin campo `name`"]
    if not fm.get("description"):
        return False, ["frontmatter sin campo `description`"]

    name = fm["name"]
    if len(name) > MAX_NAME_LEN:
        return False, [
            f"name demasiado largo: {len(name)} chars (máx {MAX_NAME_LEN})"
        ]

    desc = fm["description"]
    if len(desc) > MAX_DESCRIPTION_LEN:
        return False, [
            f"description demasiado larga: {len(desc)} chars "
            f"(máx {MAX_DESCRIPTION_LEN})"
        ]

    body_size = len(ref.raw_md.encode("utf-8"))
    if body_size > MAX_BODY_BYTES:
        return False, [
            f"SKILL.md muy grande: {body_size} bytes (máx {MAX_BODY_BYTES})"
        ]
    if body_size < MIN_BODY_BYTES:
        return False, [
            f"SKILL.md demasiado corta: {body_size} bytes "
            f"(mín {MIN_BODY_BYTES})"
        ]

    for pat in _SECRET_PATTERNS:
        if pat.search(ref.raw_md):
            return False, [
                f"posible secreto detectado en el cuerpo: patrón "
                f"{pat.pattern!r}"
            ]

    issues: list[str] = []
    if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", name) and len(name) > 1:
        issues.append(f"name '{name}' no sigue kebab-case (recomendado)")
    return True, issues


# ── Fetching: GitHub ──────────────────────────────────────────────────────

def search_github_skill_repos(
    query: str | None = None,
    min_stars: int = GH_MIN_STARS,
    limit: int = GH_DEFAULT_LIMIT_REPOS,
) -> list[dict[str, Any]]:
    """Devuelve repos candidatos como dicts con full_name, stargazers_count,
    description, default_branch, html_url. Ordenados por estrellas desc."""
    queries: list[str]
    if query:
        queries = [query]
    else:
        queries = list(GH_DEFAULT_QUERIES)

    seen: dict[str, dict[str, Any]] = {}
    for q in queries:
        url = (
            f"{GH_API_BASE}/search/repositories?"
            f"q={urllib.parse.quote(q)}&sort=stars&order=desc&"
            f"per_page={min(max(limit * 2, 10), 30)}"
        )
        try:
            data = _http_get_json(url, headers=_gh_headers())
        except (urllib.error.HTTPError, urllib.error.URLError,
                json.JSONDecodeError, TimeoutError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        for r in (data.get("items") or []):
            if not isinstance(r, dict):
                continue
            if (r.get("stargazers_count") or 0) < min_stars:
                continue
            name = r.get("full_name") or ""
            if name and name not in seen:
                seen[name] = {
                    "full_name": name,
                    "stargazers_count": r.get("stargazers_count", 0),
                    "description": (r.get("description") or "")[:300],
                    "default_branch": r.get("default_branch") or "main",
                    "html_url": r.get("html_url") or f"https://github.com/{name}",
                }
        if len(seen) >= limit:
            break
    items = sorted(seen.values(),
                   key=lambda r: r["stargazers_count"], reverse=True)
    return items[:limit]


def list_skill_files_in_repo(
    full_name: str,
    ref: str = "HEAD",
) -> list[dict[str, Any]]:
    """Lista blobs cuyo basename es `SKILL.md` (case-insensitive). Usa
    git/trees recursive=1. Si truncated, devuelve lo que se haya leído."""
    url = f"{GH_API_BASE}/repos/{full_name}/git/trees/{ref}?recursive=1"
    try:
        data = _http_get_json(url, headers=_gh_headers())
    except (urllib.error.HTTPError, urllib.error.URLError,
            json.JSONDecodeError, TimeoutError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[dict[str, Any]] = []
    tree_sha = data.get("sha", "")
    for entry in data.get("tree") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "blob":
            continue
        path = entry.get("path") or ""
        base = path.rsplit("/", 1)[-1].lower()
        if base == "skill.md":
            out.append({
                "path": path,
                "blob_sha": entry.get("sha", ""),
                "tree_sha": tree_sha,
            })
    return out[:GH_MAX_SKILLS_PER_REPO]


def fetch_blob_content(full_name: str, ref: str, path: str) -> str | None:
    """Descarga un blob como raw text desde raw.githubusercontent.com."""
    url = f"{GH_RAW_BASE}/{full_name}/{ref}/{urllib.parse.quote(path)}"
    try:
        return _http_get_text(url, max_bytes=MAX_BODY_BYTES + 1024)
    except (urllib.error.HTTPError, urllib.error.URLError,
            ValueError, TimeoutError, OSError):
        return None


def fetch_github_catalog(
    query: str | None = None,
    min_stars: int = GH_MIN_STARS,
    limit_repos: int = GH_DEFAULT_LIMIT_REPOS,
    max_skills_per_repo: int = GH_MAX_SKILLS_PER_REPO,
) -> Iterator[SkillRef]:
    """Generator de `SkillRef` por cada SKILL.md encontrada en repos top."""
    repos = search_github_skill_repos(
        query=query, min_stars=min_stars, limit=limit_repos
    )
    for repo in repos:
        full_name = repo["full_name"]
        default_branch = repo["default_branch"]
        files = list_skill_files_in_repo(full_name, default_branch)
        files = files[:max_skills_per_repo]
        for f in files:
            content = fetch_blob_content(full_name, default_branch, f["path"])
            if content is None or not content.strip():
                continue
            fm = parse_frontmatter(content) or {}
            name = fm.get("name") or Path(f["path"]).parent.name or "unnamed"
            description = (
                fm.get("description")
                or repo["description"][:MAX_DESCRIPTION_LEN]
            )
            yield SkillRef(
                name=name,
                description=description,
                source="github",
                source_url=(
                    f"https://github.com/{full_name}/blob/"
                    f"{default_branch}/{f['path']}"
                ),
                sha=(f["blob_sha"] or "")[:12],
                raw_md=content,
                kind="awesome" if "awesome" in full_name.lower() else "library",
                extra={
                    "repo": full_name,
                    "stars": repo["stargazers_count"],
                    "path": f["path"],
                },
            )


# ── Fetching: library-skills CLI (tiangolo) ──────────────────────────────

def has_library_skills_cli() -> bool:
    return bool(shutil.which("uvx") or shutil.which("library-skills"))


def fetch_library_skills_local(
    project_root: Path | str,
) -> list[SkillRef]:
    """Si el proyecto tiene `pyproject.toml` o `package.json`, ejecuta
    `uvx library-skills --dry-run --claude` y captura las skills detectadas.

    El CLI de tiangolo escanea las dependencias instaladas y reporta qué
    librerías traen skills embebidas. Best-effort: si el CLI no está
    disponible o falla, devuelve [].
    """
    root = Path(project_root)
    has_marker = (
        (root / "pyproject.toml").exists()
        or (root / "package.json").exists()
    )
    if not has_marker:
        return []
    if not has_library_skills_cli():
        return []
    cmd: list[str]
    if shutil.which("uvx"):
        cmd = ["uvx", "library-skills", "--dry-run", "--claude"]
    else:
        cmd = ["library-skills", "--dry-run", "--claude"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    return _parse_library_skills_dry_run(proc.stdout, root)


def _parse_library_skills_dry_run(
    stdout: str,
    project_root: Path,
) -> list[SkillRef]:
    """Defensivo: el formato del CLI puede cambiar entre versiones. Intentamos
    extraer líneas con shape `lib_name (skill_name) — description`. Lo que no
    matche se ignora silenciosamente.

    Como no podemos descargar el SKILL.md sin instalar la librería, cada ref
    devuelve un wrapper informativo con instrucciones de activación. La
    aprobación crea un SKILL.md placeholder; la skill real vive en el paquete.
    """
    out: list[SkillRef] = []
    line_re = re.compile(
        r"^([a-zA-Z0-9_\-]+)\s*\(([a-zA-Z0-9_\-]+)\)\s*[—:\-]+\s*(.+)$"
    )
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = line_re.match(line)
        if not m:
            continue
        lib, skill_name, desc = m.group(1), m.group(2), m.group(3).strip()
        desc = desc[:MAX_DESCRIPTION_LEN]
        skill_id = f"pkg-{lib}-{skill_name}"[:MAX_NAME_LEN]
        raw_md = (
            f"---\n"
            f"name: {skill_id}\n"
            f"description: {desc or f'Skill from {lib}'}\n"
            f"---\n\n"
            f"# {skill_name} (from `{lib}`)\n\n"
            f"Skill embebida en el paquete `{lib}`. Para activarla en este "
            f"proyecto:\n\n"
            f"```bash\n"
            f"cd {project_root}\n"
            f"uvx library-skills --claude\n"
            f"```\n\n"
            f"Esto crea un symlink en `.claude/skills/` apuntando al "
            f"`SKILL.md` que viaja dentro del paquete `{lib}` instalado, "
            f"manteniéndola sincronizada con la versión actual de la "
            f"librería.\n"
        )
        out.append(SkillRef(
            name=skill_id,
            description=desc or f"Skill from {lib}",
            source="pkg",
            source_url=f"https://library-skills.io/use/?lib={lib}",
            sha=lib,
            raw_md=raw_md,
            kind="library",
            extra={"library": lib, "skill_name": skill_name},
        ))
    return out


# ── Persistencia y dedup ──────────────────────────────────────────────────

def proposals_dir(project_root: Path | str) -> Path:
    return Path(project_root) / ".apex" / "skill-proposals"


def context_db_path(project_root: Path | str) -> Path:
    return Path(project_root) / ".apex" / "context.db"


def is_already_imported(db_path: Path, slug: str, sha: str) -> bool:
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return False
    try:
        row = conn.execute(
            "SELECT sha FROM library_imports WHERE slug=?",
            (slug,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()
    if row is None:
        return False
    return (row[0] or "") == (sha or "")


def mark_imported(db_path: Path, ref: SkillRef,
                  status: str = "proposed") -> None:
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.OperationalError:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO library_imports "
            "(slug, source, source_url, sha, imported_at, status) "
            "VALUES (?, ?, ?, ?, datetime('now'), ?)",
            (ref.slug(), ref.source, ref.source_url, ref.sha, status),
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


def is_rejected(db_path: Path, slug: str) -> bool:
    """Reusa la tabla `skill_forge_rejections` del Sprint 11.2."""
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM skill_forge_rejections WHERE slug=?",
            (slug,),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def write_proposal(prop: LibraryProposal,
                   project_root: Path | str) -> Path:
    out_dir = proposals_dir(project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{prop.slug}.md"
    path.write_text(prop.to_markdown(), encoding="utf-8")
    return path


# ── Pipeline ──────────────────────────────────────────────────────────────

def ingest(
    project_root: Path | str,
    source: str = "both",          # "github" | "pkg" | "both"
    query: str | None = None,
    min_stars: int = GH_MIN_STARS,
    limit_repos: int = GH_DEFAULT_LIMIT_REPOS,
    max_skills_per_repo: int = GH_MAX_SKILLS_PER_REPO,
    refs_override: list[SkillRef] | None = None,
) -> IngestResult:
    """Pipeline completo. Side-effects: `.apex/skill-proposals/` y tabla
    `library_imports`. Sin red si `refs_override` se pasa (usado por tests).
    """
    res = IngestResult()
    db = context_db_path(project_root)

    refs: list[SkillRef] = []
    if refs_override is not None:
        refs.extend(refs_override)
        res.sources_used.append("override")
    else:
        if source in ("github", "both"):
            res.sources_used.append("github")
            for r in fetch_github_catalog(
                query=query, min_stars=min_stars,
                limit_repos=limit_repos,
                max_skills_per_repo=max_skills_per_repo,
            ):
                refs.append(r)
            res.repos_searched = len({
                r.extra.get("repo", "") for r in refs if r.source == "github"
            })

        if source in ("pkg", "both"):
            pkg_refs = fetch_library_skills_local(project_root)
            if pkg_refs:
                res.sources_used.append("pkg")
                refs.extend(pkg_refs)

    seen_slugs: set[str] = set()
    for ref in refs:
        slug = ref.slug()
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        if is_rejected(db, slug):
            res.rejected.append(slug)
            continue
        if is_already_imported(db, slug, ref.sha):
            res.already_imported.append(slug)
            continue

        proposal_path = proposals_dir(project_root) / f"{slug}.md"
        if proposal_path.exists():
            res.already_proposed.append(slug)
            continue

        valid, issues = validate_skill(ref)
        if not valid:
            res.invalid.append((slug, "; ".join(issues)))
            continue

        prop = LibraryProposal(ref=ref, issues=issues)
        write_proposal(prop, project_root)
        mark_imported(db, ref, status="proposed")
        res.written.append(slug)

    return res


def reset_visit_counter(hub_db_path: Path | str) -> None:
    """Llamado tras una ingesta exitosa: limpia el set de proyectos visitados
    en `hub.db` (`global_meta.library_ingest_visit_set`) para que el
    recordatorio del session-start hook no dispare en los próximos N proyectos.
    """
    p = Path(hub_db_path)
    if not p.exists():
        return
    try:
        conn = sqlite3.connect(str(p))
    except sqlite3.OperationalError:
        return
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS global_meta ("
            "key TEXT PRIMARY KEY, value TEXT, "
            "updated_at TEXT DEFAULT (datetime('now')))"
        )
        conn.execute(
            "INSERT OR REPLACE INTO global_meta (key, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            ("library_ingest_visit_set", json.dumps([])),
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
