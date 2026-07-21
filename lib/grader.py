"""Grader outcome-based de APEX (Sprint 8).

Reemplaza el flow-guardian checklist por evaluación de outcomes verificables.
Política híbrida:

1. **Checks deterministas** (programáticos, rápidos, sin LLM) corren primero.
   Si alguno crítico falla → block automático sin gastar tokens.
2. **Juicio LLM** (Sonnet 4.6) sólo se invoca cuando los hechos básicos están
   en orden. El juez emite quality 1-4 + issues cualitativas.
3. El verdict final = merge(determinista, llm). El bloqueo determinista nunca
   se relaja por el LLM.

Razón: el N estadístico de Vicente es 1 usuario × ~10 sesiones/semana — un
panel tri-judge CREAO sería overkill. Sonnet 4.6 único, con caché de prompt,
es la decisión arquitectónica registrada en `project_apex_roadmap_2026.md`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ── Taxonomía de issues ───────────────────────────────────────────────────

ISSUE_INCOMPLETE = "incomplete"
ISSUE_MOCK_DATA = "mock_data"
ISSUE_NO_GIT = "no_git_init"
ISSUE_NO_TESTS = "missing_tests"
ISSUE_NO_E2E = "no_e2e_for_ui"
ISSUE_NO_SCHEMA = "no_schema_contract"
ISSUE_NO_SO_CHECK = "no_so_detection"
ISSUE_EMOJI = "emoji_in_frontend"
ISSUE_NO_CROSS_PROJECT = "no_cross_project_search"
ISSUE_HALLUCINATION = "hallucination"
ISSUE_AMBIGUOUS = "ambiguous_outcome"

# Quality
QUALITY_POOR = 1
QUALITY_ACCEPTABLE = 2
QUALITY_GOOD = 3
QUALITY_EXCELLENT = 4

# Bloqueo automático: estos issues nunca pueden coexistir con avance de fase
BLOCKING_ISSUES = {
    ISSUE_NO_GIT,
    ISSUE_MOCK_DATA,
    ISSUE_NO_E2E,
    ISSUE_EMOJI,
}

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF]"      # pictogramas y símbolos
    "|[\U0001F600-\U0001F64F]"     # emoticonos
    "|[\U0001F680-\U0001F6FF]"     # transporte
    "|[\U0001F900-\U0001F9FF]"     # suplemento
    "|[☀-➿]"             # misc symbols
)

_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__",
              "dist", "build", ".next", ".git"}


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class Evidence:
    """Snapshot del estado del proyecto al evaluar una fase."""
    project_root: Path
    phase: int
    component_types: list[str]   # ej. ["web", "cli", "mcp"]
    git_initialized: bool
    git_diff_summary: str
    test_files: list[str]
    frontend_files: list[str]
    decisions_metadata: dict[str, Any]
    has_pydantic_models: bool
    has_playwright_tests: bool
    last_session_log: str = ""

    def hash(self) -> str:
        payload = json.dumps({
            "phase": self.phase,
            "git": self.git_initialized,
            "tests": sorted(self.test_files),
            "frontend": sorted(self.frontend_files),
            "decisions": self.decisions_metadata,
            "components": sorted(self.component_types),
        }, sort_keys=True, default=str)
        return hashlib.sha1(payload.encode()).hexdigest()[:16]


@dataclass
class Verdict:
    phase: int
    quality: int
    should_block: bool
    issues: list[str] = field(default_factory=list)
    reasoning: str = ""
    deterministic_checks: dict[str, bool] = field(default_factory=dict)
    llm_judged: bool = False
    category: str | None = None
    evidence_hash: str | None = None

    def to_db_kwargs(self) -> dict:
        return {
            "phase": self.phase,
            "quality": self.quality,
            "should_block": self.should_block,
            "issues": self.issues,
            "reasoning": self.reasoning,
            "deterministic_checks": self.deterministic_checks,
            "llm_judged": self.llm_judged,
            "category": self.category,
            "evidence_hash": self.evidence_hash,
        }


# ── Recolección de evidencia ──────────────────────────────────────────────

def _walk_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if any(p.match(pat) for pat in patterns):
            out.append(p)
    return out


def gather_evidence(
    project_root: Path | str,
    phase: int,
    component_types: list[str] | None = None,
    decisions_metadata: dict | None = None,
    last_session_log: str = "",
) -> Evidence:
    root = Path(project_root).resolve()
    git_initialized = (root / ".git").is_dir()

    git_diff = ""
    if git_initialized:
        try:
            git_diff = subprocess.run(
                ["git", "-C", str(root), "diff", "--stat", "HEAD"],
                capture_output=True, text=True, timeout=5,
            ).stdout[:2000]
        except Exception:
            pass

    test_paths = _walk_files(root, (
        "test_*.py", "*_test.py",
        "*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx",
    ))
    test_files = [str(p.relative_to(root)) for p in test_paths]

    frontend_files: list[str] = []
    fe_root = root / "frontend"
    if fe_root.exists():
        fe_paths = _walk_files(fe_root, ("*.tsx", "*.jsx", "*.vue", "*.svelte"))
        frontend_files = [str(p.relative_to(root)) for p in fe_paths]

    has_pydantic = False
    for p in _walk_files(root, ("*.py",))[:300]:
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        if "pydantic" in text and "BaseModel" in text:
            has_pydantic = True
            break

    has_playwright = False
    for pkg in root.rglob("package.json"):
        if any(part in _SKIP_DIRS for part in pkg.parts):
            continue
        try:
            text = pkg.read_text(errors="ignore")
            if "playwright" in text.lower():
                has_playwright = True
                break
        except Exception:
            continue
    if not has_playwright:
        if list(root.rglob("playwright.config.*")):
            has_playwright = True

    return Evidence(
        project_root=root,
        phase=phase,
        component_types=component_types or [],
        git_initialized=git_initialized,
        git_diff_summary=git_diff,
        test_files=test_files,
        frontend_files=frontend_files,
        decisions_metadata=decisions_metadata or {},
        has_pydantic_models=has_pydantic,
        has_playwright_tests=has_playwright,
        last_session_log=last_session_log,
    )


# ── Checks deterministas ──────────────────────────────────────────────────

def _emojis_present(frontend_files: list[str], project_root: Path) -> bool:
    for fp in frontend_files[:200]:
        try:
            text = (project_root / fp).read_text(errors="ignore")
        except Exception:
            continue
        if EMOJI_RE.search(text):
            return True
    return False


def run_deterministic_checks(evidence: Evidence) -> dict[str, bool]:
    """Devuelve {check_name: passed}. Phase-aware: cada check se aplica desde
    la fase mínima donde tiene sentido."""
    phase = evidence.phase
    checks: dict[str, bool] = {}

    if phase >= 1:
        checks["os_detected"] = bool(evidence.decisions_metadata.get("detected_os"))

    if phase >= 2 and evidence.frontend_files:
        checks["no_emojis_in_frontend"] = not _emojis_present(
            evidence.frontend_files, evidence.project_root)

    if phase >= 5:
        checks["git_initialized"] = evidence.git_initialized

    if phase >= 6:
        checks["tests_present"] = len(evidence.test_files) > 0

    if phase >= 7:
        checks["schema_contracts"] = evidence.has_pydantic_models

    if phase >= 8 and "web" in evidence.component_types:
        checks["e2e_for_web_ui"] = evidence.has_playwright_tests

    return checks


_CHECK_TO_ISSUE = {
    "git_initialized": ISSUE_NO_GIT,
    "tests_present": ISSUE_NO_TESTS,
    "os_detected": ISSUE_NO_SO_CHECK,
    "no_emojis_in_frontend": ISSUE_EMOJI,
    "schema_contracts": ISSUE_NO_SCHEMA,
    "e2e_for_web_ui": ISSUE_NO_E2E,
}


def deterministic_to_issues(checks: dict[str, bool]) -> list[str]:
    return [_CHECK_TO_ISSUE[k] for k, ok in checks.items()
            if not ok and k in _CHECK_TO_ISSUE]


# ── Evaluación principal ──────────────────────────────────────────────────

def evaluate_deterministic(evidence: Evidence) -> Verdict:
    checks = run_deterministic_checks(evidence)
    issues = deterministic_to_issues(checks)
    blocking = any(i in BLOCKING_ISSUES for i in issues)

    if blocking:
        quality = QUALITY_POOR
        reasoning = (
            f"Checks deterministas críticos fallaron en fase {evidence.phase}: "
            f"{', '.join(issues)}. Resolver antes de cerrar fase."
        )
    elif issues:
        quality = QUALITY_ACCEPTABLE
        reasoning = (
            f"Avisos deterministas no-bloqueantes: {', '.join(issues)}."
        )
    else:
        quality = QUALITY_GOOD
        reasoning = "Todos los checks deterministas pasaron."

    return Verdict(
        phase=evidence.phase,
        quality=quality,
        should_block=blocking,
        issues=issues,
        reasoning=reasoning,
        deterministic_checks=checks,
        llm_judged=False,
        evidence_hash=evidence.hash(),
    )


def build_llm_judge_prompt(evidence: Evidence,
                           deterministic: Verdict) -> str:
    """Genera prompt para juez Sonnet 4.6. Self-contained."""
    return f"""Actúa como juez objetivo evaluando el cierre de la fase {evidence.phase} de un proyecto APEX.

## Contexto
- Tipos de componente: {evidence.component_types or '(no especificado)'}
- Git inicializado: {evidence.git_initialized}
- Test files: {len(evidence.test_files)}
- Frontend files: {len(evidence.frontend_files)}
- Pydantic models: {evidence.has_pydantic_models}
- Playwright presente: {evidence.has_playwright_tests}
- Diff resumen:
{evidence.git_diff_summary[:600] or '(sin diff)'}

- Último session log:
{(evidence.last_session_log or '(sin log)')[:800]}

## Verdict determinista (ya calculado, no relajar)
- Quality: {deterministic.quality}
- Issues: {deterministic.issues}
- Should block: {deterministic.should_block}

## Tu tarea
Devuelve SÓLO un JSON con este schema, sin texto adicional:

{{
  "quality": 1|2|3|4,
  "category": "coding|design|integration|deploy|testing|other",
  "additional_issues": ["incomplete"|"mock_data"|"hallucination"|"ambiguous_outcome", ...],
  "should_block": true|false,
  "reasoning": "2-3 frases sobre si el outcome real se logró o si hay señales de cáscara/mock/incompleto"
}}

Reglas:
- quality=4 (excellent) sólo si outcome verificable + tests pasando + sin issues
- quality=1 (poor) si ves mock data, cáscara, o el outcome es fingido
- Si determinista.should_block es true, no lo relajes (pon el tuyo a true también)"""


def parse_llm_verdict(text: str) -> dict:
    """Parser tolerante: extrae el primer bloque JSON y valida contra schema.

    Returns validated dict or {} if parse/validation fails.
    """
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}

    # Validate against expected schema
    return _validate_verdict(parsed)


# JSON Schema for LLM verdict validation
_VERDICT_SCHEMA = {
    "type": "object",
    "required": ["quality", "should_block", "reasoning"],
    "properties": {
        "quality": {"type": "integer", "minimum": 1, "maximum": 4},
        "category": {
            "type": "string",
            "enum": ["coding", "design", "integration", "deploy", "testing", "other"],
        },
        "additional_issues": {
            "type": "array",
            "items": {"type": "string"},
        },
        "should_block": {"type": "boolean"},
        "reasoning": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

_VALID_CATEGORIES = {"coding", "design", "integration", "deploy", "testing", "other"}


def _validate_verdict(parsed: dict) -> dict:
    """Valida el verdict del LLM. Devuelve {} sólo si es inservible.

    El parser es TOLERANTE por contrato: un verdict al que le falte un campo
    opcional se normaliza, no se tira. Descartarlo entero (como hacía la
    versión estricta) convierte una respuesta parcialmente buena en silencio,
    que es justo lo que el grader no debe hacer.

    Sólo `quality` es imprescindible: sin ella no hay verdict que interpretar.
    """
    if not isinstance(parsed, dict):
        return {}

    if "quality" not in parsed:
        return {}

    # quality: int 1-4. Fuera de rango sí invalida: no hay lectura sensata.
    try:
        q = int(parsed["quality"])
        if q < 1 or q > 4:
            return {}
        parsed["quality"] = q
    except (TypeError, ValueError):
        return {}

    # should_block: si falta o no es bool, se asume el lado seguro (no bloquear)
    if not isinstance(parsed.get("should_block"), bool):
        parsed["should_block"] = False

    # reasoning: si falta, queda vacío en vez de invalidar el verdict
    if not isinstance(parsed.get("reasoning"), str):
        parsed["reasoning"] = ""

    # category: optional, must be in allowed set
    if "category" in parsed:
        cat = parsed["category"]
        if cat not in _VALID_CATEGORIES:
            parsed["category"] = "other"

    # additional_issues: optional, list of strings
    if "additional_issues" in parsed:
        issues = parsed["additional_issues"]
        if not isinstance(issues, list):
            parsed["additional_issues"] = []
        else:
            parsed["additional_issues"] = [
                str(i) for i in issues if isinstance(i, (str, int))
            ]

    return parsed


def merge_verdicts(determinista: Verdict, llm: dict) -> Verdict:
    """Combina determinista + LLM. El bloqueo determinista nunca se relaja."""
    if not llm:
        return determinista

    extra = list(llm.get("additional_issues", []) or [])
    all_issues = sorted(set(determinista.issues + extra))

    final_block = determinista.should_block or bool(llm.get("should_block", False))

    if final_block:
        quality = QUALITY_POOR
    else:
        try:
            llm_q = int(llm.get("quality", QUALITY_GOOD))
        except (TypeError, ValueError):
            llm_q = QUALITY_GOOD
        quality = max(min(llm_q, QUALITY_EXCELLENT), QUALITY_ACCEPTABLE)

    reasoning = llm.get("reasoning") or determinista.reasoning

    return Verdict(
        phase=determinista.phase,
        quality=quality,
        should_block=final_block,
        issues=all_issues,
        reasoning=reasoning,
        deterministic_checks=determinista.deterministic_checks,
        llm_judged=True,
        category=llm.get("category"),
        evidence_hash=determinista.evidence_hash,
    )


# ── Wrapper opcional con Anthropic SDK ───────────────────────────────────

def judge_with_anthropic(prompt: str, model: str = "claude-sonnet-4-6") -> dict:
    """Llama a Anthropic SDK si está disponible y hay API key.
    Devuelve dict parseado o {} si no se puede invocar.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {}
    try:
        import anthropic  # type: ignore
    except ImportError:
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        return parse_llm_verdict(text)
    except Exception:
        return {}


def evaluate_full(evidence: Evidence,
                  use_anthropic: bool = True) -> Verdict:
    """Evaluación completa: deterministic + LLM si hay API key.

    Si los deterministas bloquean, no se invoca al LLM (ahorra tokens).
    """
    determinista = evaluate_deterministic(evidence)

    if determinista.should_block:
        return determinista  # no gastes LLM en algo ya bloqueado

    if not use_anthropic:
        return determinista

    prompt = build_llm_judge_prompt(evidence, determinista)
    llm_dict = judge_with_anthropic(prompt)
    return merge_verdicts(determinista, llm_dict)
