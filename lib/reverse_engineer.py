"""Scanner code-first para reverse-engineering de proyectos existentes.

Principio: el CÓDIGO manda. README.md y CLAUDE.md son pistas secundarias;
si difieren del código detectado, se emite un finding "docs desactualizadas".

Produce un ScanReport con:
- Completeness matrix por fase (0-14 + gate 10.5).
- Findings retroactivos (cosas que /apex habría bloqueado si el proyecto
  se hubiera construido desde 0).
- Anti-patterns cross-project (reglas en commands/rules/errors-to-avoid.md).
- Docs vs code diff (README hace afirmaciones que el código no respalda).

Sin LLM. Sin red. Solo filesystem + git + regex.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


PhaseStatus = Literal["completed", "partial", "missing", "unknown"]
Severity = Literal["high", "medium", "low"]


@dataclass
class PhaseEvidence:
    phase: float  # 0..14 o 10.5
    name: str
    status: PhaseStatus
    score: float  # 0..1
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class RetroactiveFinding:
    id: str
    phase: float
    severity: Severity
    title: str
    detail: str
    file: str | None = None
    line: int | None = None


@dataclass
class AntiPattern:
    id: str
    rule: str
    occurrences: list[tuple[str, int, str]] = field(default_factory=list)


@dataclass
class ScanReport:
    project_path: str
    project_name: str
    meta: dict
    phases: list[PhaseEvidence]
    findings: list[RetroactiveFinding]
    anti_patterns: list[AntiPattern]
    docs_vs_code: dict

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# --- Utilidades de escaneo ---


def _run(cmd: list[str], cwd: Path, timeout: int = 10) -> str:
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
        )
        return r.stdout
    except Exception:
        return ""


def _git_tracked_files(path: Path) -> list[Path]:
    out = _run(["git", "ls-files"], path)
    if not out:
        return []
    return [path / f for f in out.strip().splitlines() if f]


def _git_age_days(path: Path) -> int | None:
    out = _run(["git", "log", "--reverse", "--format=%ct", "-1"], path)
    if not out:
        return None
    try:
        import time
        first = int(out.strip().split()[0])
        return int((time.time() - first) / 86400)
    except Exception:
        return None


def _git_last_commit_days(path: Path) -> int | None:
    out = _run(["git", "log", "-1", "--format=%ct"], path)
    if not out:
        return None
    try:
        import time
        last = int(out.strip())
        return int((time.time() - last) / 86400)
    except Exception:
        return None


def _detect_language(files: list[Path]) -> str:
    counts: dict[str, int] = {}
    for f in files:
        ext = f.suffix.lower()
        if ext in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt"}:
            counts[ext] = counts.get(ext, 0) + 1
    if not counts:
        return "unknown"
    top = max(counts, key=counts.get)
    return {
        ".py": "python", ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript", ".go": "go",
        ".rs": "rust", ".java": "java", ".kt": "kotlin",
    }.get(top, top)


def _grep_code(path: Path, pattern: str, glob: str = "*", extra: list[str] | None = None,
               pcre: bool = False) -> list[tuple[str, int, str]]:
    """Usa git grep con POSIX ERE (-E) o PCRE (-P) si pcre=True.

    Usa PCRE para rangos Unicode de emoji y otros casos que ERE no soporta.
    """
    flag = "-P" if pcre else "-E"
    cmd = ["git", "grep", "-n", flag, pattern]
    if extra:
        cmd.extend(extra)
    out = _run(cmd, path)
    if not out:
        return []
    hits = []
    for line in out.strip().splitlines()[:50]:  # cap
        parts = line.split(":", 2)
        if len(parts) == 3:
            hits.append((parts[0], int(parts[1]), parts[2][:200]))
    return hits


def _file_exists(path: Path, *candidates: str) -> Path | None:
    for c in candidates:
        p = path / c
        if p.exists():
            return p
    return None


def _any_exists(path: Path, *patterns: str) -> bool:
    for p in patterns:
        if list(path.glob(p)):
            return True
    return False


# --- Heurísticas por fase ---


def check_phase_0(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    readme = _file_exists(path, "README.md", "readme.md", "README.rst", "Readme.md")
    if readme:
        content = readme.read_text(errors="ignore").lower()
        if any(k in content for k in ["problema", "motivation", "why", "problem"]):
            ev.append(f"{readme.name} contiene contexto del problema")
            score = 0.6
            if any(k in content for k in ["competidor", "alternativa", "vs ", "existing"]):
                ev.append("README menciona análisis de competidores/alternativas")
                score = 0.9
        else:
            miss.append("README no referencia problema/motivación; ronda socrática probablemente saltada")
            score = 0.3
    else:
        miss.append("Sin README: probablemente ronda 0 nunca ocurrió")
        score = 0.0
    status: PhaseStatus = "completed" if score >= 0.8 else "partial" if score >= 0.4 else "missing"
    return PhaseEvidence(0, "socratic", status, score, ev, miss)


def check_phase_1(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    kind = []
    # Root manifests
    pkg_files = [path / "package.json", path / "pyproject.toml", path / "requirements.txt"]
    # Monorepo: apps/*, packages/*, services/*
    monorepo_dirs = []
    for d in ("apps", "packages", "services"):
        if (path / d).is_dir():
            monorepo_dirs.append(d)
            for sub in (path / d).iterdir():
                if sub.is_dir():
                    for mf in ("package.json", "pyproject.toml", "requirements.txt"):
                        if (sub / mf).exists():
                            pkg_files.append(sub / mf)
    if monorepo_dirs:
        ev.append(f"Monorepo detectado: {', '.join(monorepo_dirs)}/")

    for mf in pkg_files:
        if not mf.exists():
            continue
        c = mf.read_text(errors="ignore").lower()
        if "next" in c: kind.append("web-app (next)")
        if "vite" in c: kind.append("web-app (vite)")
        if "express" in c or "fastify" in c: kind.append("backend (node)")
        if "telegraf" in c or "discord.js" in c: kind.append("bot")
        if "fastapi" in c or "flask" in c or "django" in c: kind.append("backend (python)")
        if "telegram-bot" in c or "discord" in c: kind.append("bot (python)")
        if "mcp" in c: kind.append("mcp-server")
        if "streamlit" in c: kind.append("streamlit-ui")
    if _file_exists(path, "Cargo.toml"): kind.append("rust")
    if _file_exists(path, "go.mod"): kind.append("go")

    # Dedup
    kind = list(dict.fromkeys(kind))
    if kind:
        ev.append(f"Tipo detectado: {', '.join(kind)}")
        score = 0.9
    else:
        miss.append("No se detecta tipo de proyecto claro en root ni monorepo subdirs")
        score = 0.3
    return PhaseEvidence(1, "solution-type", "completed" if score >= 0.8 else "partial", score, ev, miss)


def check_phase_2(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    design = _file_exists(path, "DESIGN.md", "docs/DESIGN.md", "docs/design.md")
    if design:
        ev.append(f"{design.relative_to(path)} existe"); score += 0.3
    else:
        miss.append("Sin DESIGN.md ni docs/DESIGN.md")
    tw = _file_exists(path, "tailwind.config.ts", "tailwind.config.js", "tailwind.config.mjs")
    if tw:
        c = tw.read_text(errors="ignore")
        if "theme" in c and ("extend" in c or "colors" in c):
            ev.append("tailwind.config con theme extendido"); score += 0.2
    # CSS globals with @theme or :root vars
    for cssfile in path.glob("**/globals.css"):
        c = cssfile.read_text(errors="ignore")
        if "@theme" in c or "--color" in c or ":root" in c:
            ev.append(f"tokens en {cssfile.relative_to(path)}"); score += 0.2
            break
    # Uso de icon library vs emojis (PCRE para rangos unicode)
    emoji_hits = _grep_code(path, r"[\x{1F300}-\x{1F9FF}\x{2600}-\x{27BF}]",
                            extra=["--", "*.tsx", "*.jsx", "*.ts", "*.js"], pcre=True)
    if emoji_hits:
        miss.append(f"{len(emoji_hits)} emojis detectados en UI (viola regla absoluta #5)")
    else:
        ev.append("No se detectan emojis como iconos"); score += 0.15
    lucide = _grep_code(path, "lucide-react|@heroicons|phosphor-react", extra=["--", "package.json"])
    if lucide:
        ev.append("Icon library profesional importada"); score += 0.15
    return PhaseEvidence(2, "design", "completed" if score >= 0.8 else "partial" if score >= 0.3 else "missing", min(score, 1.0), ev, miss)


def check_phase_3(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    spec = _file_exists(path, "SPEC.md", "docs/SPEC.md", "docs/spec.md")
    if spec:
        content = spec.read_text(errors="ignore")
        if len(content) > 500:
            ev.append(f"{spec.relative_to(path)} ({len(content)} chars)"); score += 0.5
    else:
        miss.append("Sin SPEC.md formal")
    # Data model
    has_schema = (
        _any_exists(path, "prisma/schema.prisma", "alembic.ini", "migrations/**/*.sql")
        or _any_exists(path, "**/models/*.py", "**/entities/*.py", "**/schemas/*.py")
    )
    if has_schema:
        ev.append("Modelo de datos detectado (prisma/alembic/models)"); score += 0.4
    else:
        miss.append("No se detecta modelo de datos formal")
    return PhaseEvidence(3, "spec", "completed" if score >= 0.8 else "partial" if score >= 0.3 else "missing", min(score, 1.0), ev, miss)


def check_phase_4(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    edge = _file_exists(path, "EDGE-CASES.md", "docs/EDGE-CASES.md", "docs/edge-cases.md")
    if edge:
        ev.append(f"{edge.relative_to(path)} existe"); score += 0.6
    else:
        miss.append("Sin EDGE-CASES.md")
    # Tests con nombres de edge
    edge_tests = _grep_code(path, "test_.*(invalid|error|edge|empty|boundary|overflow|timeout)", extra=["--", "*.py", "*.ts", "*.js"])
    if edge_tests:
        ev.append(f"{len(edge_tests)} tests con nombre edge-case"); score += 0.4
    else:
        miss.append("Sin tests con nombres edge-case (invalid/error/edge/boundary)")
    return PhaseEvidence(4, "edge-cases", "completed" if score >= 0.8 else "partial" if score >= 0.3 else "missing", min(score, 1.0), ev, miss)


def check_phase_5(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    # Hexagonal signals
    hex_dirs = ["domain", "ports", "adapters", "application", "core", "infrastructure"]
    found_hex = [d for d in hex_dirs if list(path.glob(f"**/{d}/"))]
    if len(found_hex) >= 3:
        ev.append(f"Estructura hexagonal detectada: {', '.join(found_hex)}"); score += 0.5
    else:
        miss.append(f"Estructura hexagonal incompleta (solo {found_hex}). Posible monolito.")
    env_example = _file_exists(path, ".env.example", ".env.sample")
    if env_example:
        ev.append(".env.example presente"); score += 0.15
    else:
        miss.append("Sin .env.example")
    # Linter config
    has_linter = _any_exists(
        path, ".eslintrc*", "eslint.config.*", "ruff.toml", "pyproject.toml", ".flake8"
    )
    if has_linter:
        ev.append("Config de linter detectada"); score += 0.15
    # TS strict
    tsconfig = _file_exists(path, "tsconfig.json")
    if tsconfig and "\"strict\": true" in tsconfig.read_text(errors="ignore"):
        ev.append("TypeScript strict mode activo"); score += 0.2
    return PhaseEvidence(5, "scaffold", "completed" if score >= 0.8 else "partial" if score >= 0.3 else "missing", min(score, 1.0), ev, miss)


def check_phase_6(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    core_files = list(path.glob("**/domain/**/*")) + list(path.glob("**/core/**/*"))
    if len(core_files) > 3:
        ev.append(f"{len(core_files)} archivos en domain/core"); score = 0.7
    else:
        miss.append("Poca separación de dominio detectada")
    # Signals of SMA
    sma_hits = _grep_code(path, "orchestrator|agent|worker|pipeline", extra=["--", "*.py", "*.ts"])
    if sma_hits:
        ev.append(f"{len(sma_hits)} referencias a orchestrator/agent/worker"); score = min(score + 0.2, 1.0)
    status: PhaseStatus = "completed" if score >= 0.7 else "partial" if score > 0 else "unknown"
    return PhaseEvidence(6, "core", status, score, ev, miss)


def check_phase_7(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    infra = list(path.glob("**/infrastructure/**/*")) + list(path.glob("**/adapters/**/*"))
    if infra:
        ev.append(f"{len(infra)} archivos en infrastructure/adapters"); score = 0.7
    else:
        miss.append("Sin directorio infrastructure/adapters")
    migrations = list(path.glob("**/migrations/**/*"))
    if migrations:
        ev.append(f"{len(migrations)} archivos de migrations"); score = min(score + 0.3, 1.0)
    return PhaseEvidence(7, "infrastructure", "completed" if score >= 0.7 else "partial" if score > 0 else "missing", score, ev, miss)


def check_phase_8(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    di = _grep_code(path, "lifespan|injector|DependencyInjection|app\\.container", extra=["--", "*.py", "*.ts"])
    if di:
        ev.append(f"{len(di)} signals de DI/lifespan"); score = 0.6
    endpoints = _grep_code(path, "@app\\.(get|post|put|delete)|router\\.(get|post)|\\.use\\(", extra=["--", "*.py", "*.ts", "*.js"])
    if endpoints:
        ev.append(f"{len(endpoints)} endpoints/handlers detectados"); score = min(score + 0.4, 1.0)
    else:
        miss.append("Sin endpoints/handlers claros (quizás es CLI, no API)")
    return PhaseEvidence(8, "integration", "completed" if score >= 0.7 else "partial" if score > 0 else "unknown", score, ev, miss)


def check_phase_9(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    test_files = list(path.glob("**/tests/**/*.py")) + list(path.glob("**/test/**/*.py")) + \
                 list(path.glob("**/__tests__/**/*.ts")) + list(path.glob("**/__tests__/**/*.tsx")) + \
                 list(path.glob("**/*.test.ts")) + list(path.glob("**/*.test.tsx")) + \
                 list(path.glob("**/*.spec.ts")) + list(path.glob("**/*.spec.tsx")) + \
                 list(path.glob("**/test_*.py"))
    # Exclude node_modules, .venv, .next
    test_files = [f for f in test_files if not any(x in str(f) for x in ("node_modules", ".venv", ".next", "dist/", "build/"))]
    if test_files:
        ev.append(f"{len(test_files)} archivos de test")
        score = 0.5 if len(test_files) < 5 else 0.8
    else:
        miss.append("Sin tests detectados (crítico)")
    # Coverage config
    if _file_exists(path, ".coveragerc") or _any_exists(path, "pyproject.toml"):
        py = _file_exists(path, "pyproject.toml")
        if py and "coverage" in py.read_text(errors="ignore"):
            ev.append("Config de coverage (pyproject)"); score = min(score + 0.1, 1.0)
    if _file_exists(path, "jest.config.js", "vitest.config.ts", "vitest.config.js"):
        ev.append("Config de jest/vitest"); score = min(score + 0.1, 1.0)
    # Playwright
    if _file_exists(path, "playwright.config.ts", "playwright.config.js"):
        ev.append("Playwright E2E configurado"); score = min(score + 0.1, 1.0)
    return PhaseEvidence(9, "testing", "completed" if score >= 0.8 else "partial" if score > 0 else "missing", score, ev, miss)


def check_phase_10(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    # .env en git?
    out = _run(["git", "ls-files"], path)
    if ".env\n" in out or out.startswith(".env\n"):
        miss.append("❗ .env trackeado en git (crítico)")
    else:
        ev.append(".env NO trackeado en git"); score += 0.2
    # CORS wildcards
    cors_wc = _grep_code(path, "CORS.*allow.*=.*\\[.*\\*.*\\]|origins=\\[['\"]\\*", extra=["--", "*.py"])
    if cors_wc:
        miss.append(f"{len(cors_wc)} CORS wildcards (violación fase 10)")
    else:
        ev.append("Sin CORS wildcard evidente"); score += 0.2
    # Hardcoded secrets
    secrets = _grep_code(path, "sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}", extra=["--", ":!.env.example", ":!*.md"])
    if secrets:
        miss.append(f"❗ {len(secrets)} secretos hardcoded")
    else:
        ev.append("Sin secretos hardcoded evidentes"); score += 0.3
    # Input validation
    validators = _grep_code(path, "Pydantic|BaseModel|zod\\.|yup\\.|joi\\.", extra=["--", "*.py", "*.ts"])
    if validators:
        ev.append(f"{len(validators)} usos de validadores (pydantic/zod/yup)"); score += 0.15
    else:
        miss.append("Sin librería de validación detectada")
    # Rate limit
    rl = _grep_code(path, "slowapi|express-rate-limit|rate.limit", extra=["--", "*.py", "*.ts"])
    if rl:
        ev.append("Rate limiting detectado"); score += 0.15
    return PhaseEvidence(10, "security", "completed" if score >= 0.8 else "partial" if score > 0.2 else "missing", min(score, 1.0), ev, miss)


def check_phase_10_5(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    sec = path / ".apex" / "security"
    if not sec.exists():
        miss.append("Sin .apex/security/ (gate no iniciado)")
        return PhaseEvidence(10.5, "agentarmor-gate", "missing", 0.0, ev, miss)
    layers = list(sec.glob("L*-*.md"))
    if len(layers) < 8:
        miss.append(f"Solo {len(layers)}/8 capas AgentArmor")
    passed = 0
    for l in layers:
        c = l.read_text(errors="ignore")
        if "status: passed" in c:
            passed += 1
    ev.append(f"{passed}/{len(layers)} capas passed")
    score = passed / 8.0
    status: PhaseStatus = "completed" if score == 1.0 else "partial" if score > 0 else "missing"
    return PhaseEvidence(10.5, "agentarmor-gate", status, score, ev, miss)


def check_phase_11(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    # Busca Dockerfile en root o subdirs comunes de monorepo
    dockerfiles = list(path.glob("Dockerfile")) + list(path.glob("apps/*/Dockerfile")) + \
                  list(path.glob("packages/*/Dockerfile")) + list(path.glob("services/*/Dockerfile"))
    if dockerfiles:
        ev.append(f"{len(dockerfiles)} Dockerfile(s) encontrado(s)"); score += 0.25
    else:
        miss.append("Sin Dockerfile en root ni monorepo subdirs")
    workflows = list(path.glob(".github/workflows/*.yml")) + list(path.glob(".github/workflows/*.yaml"))
    if workflows:
        ev.append(f"{len(workflows)} workflows GH Actions"); score += 0.25
    else:
        miss.append("Sin .github/workflows/")
    if _grep_code(path, "/health|healthcheck|health_check", extra=["--", "*.py", "*.ts", "*.tsx"]):
        ev.append("Endpoint /health detectado"); score += 0.2
    else:
        miss.append("Sin endpoint /health evidente")
    if _file_exists(path, "ROLLBACK.md", "docs/ROLLBACK.md"):
        ev.append("Rollback plan documentado"); score += 0.15
    if _file_exists(path, "docker-compose.prod.yml", "docker-compose.yml", "compose.yml", "compose.yaml"):
        ev.append("docker-compose presente"); score += 0.15
    return PhaseEvidence(11, "deploy", "completed" if score >= 0.8 else "partial" if score > 0 else "missing", min(score, 1.0), ev, miss)


def check_phase_12(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    out = _run(["git", "log", "--since=30.days", "--oneline"], path)
    commits_30d = len(out.strip().splitlines()) if out else 0
    if commits_30d > 0:
        ev.append(f"{commits_30d} commits últimos 30 días"); score = 1.0 if commits_30d >= 5 else 0.5
    else:
        miss.append("Sin commits últimos 30 días (proyecto inactivo)"); score = 0.0
    return PhaseEvidence(12, "iteration", "completed" if score >= 0.8 else "partial" if score > 0 else "missing", score, ev, miss)


def check_phase_13(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    if list(path.glob("**/prometheus.yml")) or list(path.glob("**/grafana/**")):
        ev.append("Monitoring (Prometheus/Grafana) detectado"); score += 0.5
    else:
        miss.append("Sin Prometheus/Grafana")
    cache = _grep_code(path, "redis|memcached|cache|@cached", extra=["--", "*.py", "*.ts"])
    if cache:
        ev.append(f"{len(cache)} signals de caching"); score += 0.3
    if list(path.glob("**/loki*.yml")):
        ev.append("Loki logs detectado"); score += 0.2
    return PhaseEvidence(13, "scaling", "completed" if score >= 0.8 else "partial" if score > 0 else "missing", min(score, 1.0), ev, miss)


def check_phase_14(path: Path, files: list[Path]) -> PhaseEvidence:
    ev, miss = [], []
    score = 0.0
    if _file_exists(path, "CHANGELOG.md"):
        ev.append("CHANGELOG.md presente"); score += 0.2
    else:
        miss.append("Sin CHANGELOG.md")
    if _file_exists(path, "ARCHITECTURE.md", "docs/ARCHITECTURE.md"):
        ev.append("ARCHITECTURE.md presente"); score += 0.2
    if _file_exists(path, ".github/dependabot.yml", "renovate.json"):
        ev.append("Dependabot/Renovate configurado"); score += 0.2
    backup = _grep_code(path, "backup|pg_dump|snapshot", extra=["--", "*.sh", "*.py", "*.yml"])
    if backup:
        ev.append(f"{len(backup)} signals de backup"); score += 0.2
    if _file_exists(path, "GUIDE.md", "docs/GUIDE.md", "USER_GUIDE.md"):
        ev.append("Guía de usuario presente"); score += 0.2
    return PhaseEvidence(14, "maintenance", "completed" if score >= 0.8 else "partial" if score > 0 else "missing", min(score, 1.0), ev, miss)


PHASE_CHECKERS = [
    check_phase_0, check_phase_1, check_phase_2, check_phase_3,
    check_phase_4, check_phase_5, check_phase_6, check_phase_7,
    check_phase_8, check_phase_9, check_phase_10, check_phase_10_5,
    check_phase_11, check_phase_12, check_phase_13, check_phase_14,
]


# --- Anti-patterns cross-project ---


def detect_anti_patterns(path: Path, files: list[Path]) -> list[AntiPattern]:
    patterns = []

    # Emojis en UI (PCRE para rangos unicode)
    emoji_hits = _grep_code(path, r"[\x{1F300}-\x{1F9FF}\x{2600}-\x{27BF}]",
                            extra=["--", "*.tsx", "*.jsx"], pcre=True)
    if emoji_hits:
        patterns.append(AntiPattern(
            id="AP-01", rule="Nunca emojis como iconos (regla absoluta #5)",
            occurrences=emoji_hits[:10],
        ))

    # console.log huérfanos
    cl = _grep_code(path, "console\\.log\\(", extra=["--", "*.ts", "*.tsx", "*.js", ":!*.test.*"])
    if len(cl) > 5:
        patterns.append(AntiPattern(
            id="AP-02", rule="console.log huérfanos en producción (>5 instancias)",
            occurrences=cl[:10],
        ))

    # print() en Python
    pr = _grep_code(path, "^\\s*print\\(", extra=["--", "*.py", ":!tests/*", ":!*test*"])
    if len(pr) > 5:
        patterns.append(AntiPattern(
            id="AP-03", rule="print() huérfanos en Python (>5 instancias)",
            occurrences=pr[:10],
        ))

    # TODO/FIXME viejos
    todos = _grep_code(path, "TODO|FIXME|XXX|HACK", extra=["--", "*.py", "*.ts", "*.tsx"])
    if len(todos) > 10:
        patterns.append(AntiPattern(
            id="AP-04", rule=f"TODO/FIXME acumulados ({len(todos)} instancias)",
            occurrences=todos[:10],
        ))

    # Tailwind sin theme custom (genérico)
    tw = _file_exists(path, "tailwind.config.ts", "tailwind.config.js")
    if tw:
        c = tw.read_text(errors="ignore")
        if "extend" not in c and "theme:" in c:
            patterns.append(AntiPattern(
                id="AP-05", rule="Tailwind sin theme personalizado (diseño genérico)",
                occurrences=[(str(tw.relative_to(path)), 1, c[:100])],
            ))

    # Falta de tildes en copy ES (heurística simple: archivos con texto UI sin tildes)
    # (no emitimos finding automático por alto riesgo de FP)

    return patterns


# --- Docs vs code ---


def compare_docs_vs_code(path: Path, phases: list[PhaseEvidence], language: str) -> dict:
    """Compara afirmaciones en README/CLAUDE contra el estado real del código."""
    mismatches = []
    readme = _file_exists(path, "README.md", "readme.md")
    claude = _file_exists(path, "CLAUDE.md")

    for doc_file in [readme, claude]:
        if not doc_file:
            continue
        try:
            content = doc_file.read_text(errors="ignore").lower()
        except Exception:
            continue
        # Claims comunes
        if "production" in content or "producción" in content:
            # ¿De verdad está en production?
            p11 = next(p for p in phases if p.phase == 11)
            if p11.status == "missing":
                mismatches.append(f"{doc_file.name} afirma 'producción' pero no hay Dockerfile/CI/health")
        if "test" in content and "coverage" in content:
            p9 = next(p for p in phases if p.phase == 9)
            if p9.status == "missing":
                mismatches.append(f"{doc_file.name} afirma tener tests con coverage pero no se detectan tests")
        if "hexagonal" in content or "clean architecture" in content:
            p5 = next(p for p in phases if p.phase == 5)
            if p5.score < 0.5:
                mismatches.append(f"{doc_file.name} afirma hexagonal/clean pero la estructura es plana")

    # Git age de los docs vs code
    age_info = {}
    for doc_file in [readme, claude]:
        if not doc_file:
            continue
        rel = str(doc_file.relative_to(path))
        out = _run(["git", "log", "-1", "--format=%ct", "--", rel], path)
        if out:
            try:
                import time
                doc_age_days = int((time.time() - int(out.strip())) / 86400)
                # Código (cualquier archivo .py/.ts modificado después)
                last_code = _run(["git", "log", "-1", "--format=%ct", "--", "*.py", "*.ts", "*.tsx"], path)
                if last_code:
                    code_age_days = int((time.time() - int(last_code.strip())) / 86400)
                    if doc_age_days - code_age_days > 30:
                        mismatches.append(f"{rel} no se toca hace {doc_age_days}d, código sí hace {code_age_days}d (probablemente desactualizado)")
                age_info[rel] = {"days_since_edit": doc_age_days}
            except Exception:
                pass

    return {"mismatches": mismatches, "ages": age_info}


# --- Findings retroactivos ---


def derive_findings(phases: list[PhaseEvidence], anti: list[AntiPattern]) -> list[RetroactiveFinding]:
    findings = []
    for p in phases:
        for idx, miss in enumerate(p.missing):
            sev: Severity = "high" if p.phase in (10, 10.5) and "❗" in miss else (
                "high" if p.phase in (9, 10) else "medium" if p.phase <= 11 else "low"
            )
            findings.append(RetroactiveFinding(
                id=f"F-{p.phase}-{idx+1:02d}",
                phase=p.phase,
                severity=sev,
                title=f"Fase {p.phase} ({p.name}): {miss[:60]}",
                detail=miss,
            ))
    for ap in anti:
        findings.append(RetroactiveFinding(
            id=ap.id,
            phase=-1,
            severity="medium",
            title=f"Anti-pattern: {ap.rule}",
            detail=f"{len(ap.occurrences)} ocurrencias. Primera: {ap.occurrences[0] if ap.occurrences else 'N/A'}",
        ))
    return findings


# --- Orchestrator ---


def scan_project(path: Path) -> ScanReport:
    path = path.resolve()
    files = _git_tracked_files(path)
    language = _detect_language(files) if files else "unknown"

    meta = {
        "language": language,
        "tracked_files": len(files),
        "age_days": _git_age_days(path),
        "last_commit_days": _git_last_commit_days(path),
        "has_apex": (path / ".apex").exists(),
    }

    phases = [checker(path, files) for checker in PHASE_CHECKERS]
    anti = detect_anti_patterns(path, files)
    findings = derive_findings(phases, anti)
    docs_vs = compare_docs_vs_code(path, phases, language)

    return ScanReport(
        project_path=str(path),
        project_name=path.name,
        meta=meta,
        phases=phases,
        findings=findings,
        anti_patterns=anti,
        docs_vs_code=docs_vs,
    )


def render_report_md(r: ScanReport) -> str:
    lines = [f"# Reverse-engineer scan: {r.project_name}", ""]
    lines.append(f"- Path: `{r.project_path}`")
    lines.append(f"- Lenguaje: **{r.meta['language']}**")
    lines.append(f"- Archivos tracked: {r.meta['tracked_files']}")
    if r.meta['age_days'] is not None:
        lines.append(f"- Edad del repo: {r.meta['age_days']} días")
    if r.meta['last_commit_days'] is not None:
        lines.append(f"- Último commit: hace {r.meta['last_commit_days']} días")
    lines.append(f"- APEX ya inicializado: {'sí' if r.meta['has_apex'] else 'no'}")
    lines.append("")

    # Completeness matrix
    lines.append("## Completeness por fase")
    lines.append("")
    lines.append("| Fase | Nombre             | Status     | Score |")
    lines.append("| ---- | ------------------ | ---------- | ----- |")
    for p in r.phases:
        lines.append(f"| {p.phase} | {p.name:<18} | {p.status:<10} | {p.score:.2f} |")
    lines.append("")

    # Findings
    high = [f for f in r.findings if f.severity == "high"]
    med = [f for f in r.findings if f.severity == "medium"]
    low = [f for f in r.findings if f.severity == "low"]
    lines.append(f"## Findings retroactivos ({len(r.findings)} total: {len(high)} alta · {len(med)} media · {len(low)} baja)")
    lines.append("")
    for sev_name, sev_list in [("Alta", high), ("Media", med), ("Baja", low)]:
        if not sev_list:
            continue
        lines.append(f"### {sev_name}")
        for f in sev_list[:20]:
            lines.append(f"- **{f.id}** (fase {f.phase}): {f.detail}")
        lines.append("")

    # Anti-patterns
    if r.anti_patterns:
        lines.append("## Anti-patterns detectados")
        for ap in r.anti_patterns:
            lines.append(f"- **{ap.id}**: {ap.rule} — {len(ap.occurrences)} ocurrencias")
        lines.append("")

    # Docs vs code
    if r.docs_vs_code.get("mismatches"):
        lines.append("## Docs vs código (posibles desactualizaciones)")
        for m in r.docs_vs_code["mismatches"]:
            lines.append(f"- {m}")
        lines.append("")

    lines.append("## Siguiente paso")
    lines.append("")
    lines.append("Invocar skill `brainstorming` para cada finding no-obvio, luego")
    lines.append("`AskUserQuestion` para decidir qué priorizar. Finalmente ejecutar")
    lines.append("`apex_onboard_apply(plan)` para crear `.apex/` con el estado real.")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    report = scan_project(target)
    print(render_report_md(report))
