"""SkillGenAgent -- generates Claude Code skills for designed SMA agents.

Produces SKILL.md files, slash commands, trigger keywords, and agent
definitions that integrate with Claude Code's skill system.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.domain import AgentSpec, Architecture, Skill
from core.ports import ILLMProvider, IVectorStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a Claude Code skill designer.  You create SKILL.md files that "
    "teach Claude Code how to act as a specialised agent.  Skills must include:\n"
    "- A clear trigger description\n"
    "- Step-by-step instructions\n"
    "- Anti-patterns to avoid\n"
    "- A completion checklist\n\n"
    "Always respond in valid JSON as instructed."
)

_SKILL_PROMPT = """\
Generate a Claude Code SKILL.md for the following agent within a \
{pattern} multi-agent system.

Agent specification:
- Name: {name}
- Responsibility: {responsibility}
- Input: {input_desc}
- Output: {output_desc}
- Model: {model}
- Tools: {tools}
- Dependencies: {dependencies}
- Needs RAG: {needs_rag}
- Needs Memory: {needs_memory}
- Failure mode: {failure_mode}

Architecture context:
- Pattern: {pattern}
- Communication: {communication}
- Total agents: {agent_count}
- Other agents: {other_agents}

Respond with JSON:
{{
  "name": "skill-name (kebab-case)",
  "description": "One-line description for the skill registry",
  "trigger_keywords": ["keyword1", "keyword2", "keyword3"],
  "category": "one of: auth, database, api, ui, testing, devops, styling, perf, security, docs, orchestration, agent",
  "content": "The full SKILL.md content in Markdown"
}}

The SKILL.md content must include these sections:
# {{Agent Name}} Skill

## Trigger
When to activate this skill.

## Context
What this agent does within the larger SMA.

## Instructions
Step-by-step guide for Claude Code to act as this agent.
1. ...
2. ...

## Input/Output Contract
- Input: ...
- Output: ...

## Anti-patterns
- Do NOT ...
- Avoid ...

## Integration Points
How this agent communicates with others.

## Completion Checklist
- [ ] Criteria 1
- [ ] Criteria 2
"""


class SkillGenAgent:
    """Generates Claude Code skills for each agent in a designed SMA."""

    def __init__(
        self,
        llm: ILLMProvider,
        vector_store: IVectorStore | None = None,
    ) -> None:
        self._llm = llm
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_skill(
        self,
        architecture: Architecture,
        agent_spec: AgentSpec,
        llm: ILLMProvider | None = None,
    ) -> Skill:
        """Generate a Claude Code skill for a single agent.

        Parameters
        ----------
        architecture:
            The full SMA architecture (provides context about other agents).
        agent_spec:
            The specific agent to generate a skill for.
        llm:
            Optional LLM override.

        Returns
        -------
        A ``Skill`` domain entity with populated content.
        """
        active_llm = llm or self._llm

        other_agents = [a.name for a in architecture.agents if a.name != agent_spec.name]

        prompt = _SKILL_PROMPT.format(
            name=agent_spec.name,
            responsibility=agent_spec.responsibility,
            input_desc=agent_spec.input_description,
            output_desc=agent_spec.output_description,
            model=agent_spec.recommended_model,
            tools=", ".join(agent_spec.tools) if agent_spec.tools else "none",
            dependencies=", ".join(agent_spec.dependencies) if agent_spec.dependencies else "none",
            needs_rag=agent_spec.needs_rag,
            needs_memory=agent_spec.needs_memory,
            failure_mode=agent_spec.failure_mode,
            pattern=architecture.pattern,
            communication=architecture.communication,
            agent_count=architecture.agent_count,
            other_agents=", ".join(other_agents) if other_agents else "none",
        )

        raw = await active_llm.generate(
            prompt=prompt,
            model="default",
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.6,
        )

        try:
            parsed = self._parse_json(raw)
            return self._build_skill(parsed, agent_spec)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Failed to parse SkillGen output for agent '%s': %s",
                agent_spec.name,
                exc,
            )
            return self._fallback_skill(architecture, agent_spec)

    async def generate_all_skills(
        self,
        architecture: Architecture,
        llm: ILLMProvider | None = None,
    ) -> list[Skill]:
        """Generate skills for every agent in the architecture.

        Convenience method that iterates over all agents and generates a
        skill for each one.
        """
        skills: list[Skill] = []
        for agent_spec in architecture.agents:
            skill = await self.generate_skill(
                architecture=architecture,
                agent_spec=agent_spec,
                llm=llm,
            )
            skills.append(skill)
        return skills

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_skill(data: dict[str, Any], agent_spec: AgentSpec) -> Skill:
        """Construct a ``Skill`` entity from parsed LLM JSON."""
        return Skill(
            name=data.get("name", agent_spec.name.lower().replace(" ", "-")),
            description=data.get("description", agent_spec.responsibility),
            trigger_keywords=data.get("trigger_keywords", []),
            content=data.get("content", ""),
            category=data.get("category", "agent"),
        )

    @staticmethod
    def _fallback_skill(architecture: Architecture, agent_spec: AgentSpec) -> Skill:
        """Generate a minimal skill when LLM output is unusable."""
        safe_name = agent_spec.name.lower().replace(" ", "-")
        deps = ", ".join(agent_spec.dependencies) if agent_spec.dependencies else "none"

        content = (
            f"# {agent_spec.name} Skill\n\n"
            f"## Trigger\n"
            f"Activate when working on the {agent_spec.name} agent within the "
            f"{architecture.pattern} SMA.\n\n"
            f"## Context\n"
            f"{agent_spec.responsibility}\n\n"
            f"## Instructions\n"
            f"1. Read the input: {agent_spec.input_description}\n"
            f"2. Process according to the agent's responsibility.\n"
            f"3. Produce the output: {agent_spec.output_description}\n"
            f"4. Handle failures with mode: {agent_spec.failure_mode}\n\n"
            f"## Input/Output Contract\n"
            f"- Input: {agent_spec.input_description}\n"
            f"- Output: {agent_spec.output_description}\n\n"
            f"## Anti-patterns\n"
            f"- Do NOT access infrastructure directly from domain code.\n"
            f"- Avoid coupling to specific LLM providers.\n\n"
            f"## Integration Points\n"
            f"- Dependencies: {deps}\n"
            f"- Communication: {architecture.communication}\n\n"
            f"## Completion Checklist\n"
            f"- [ ] Agent processes input correctly\n"
            f"- [ ] Error handling implemented ({agent_spec.failure_mode})\n"
            f"- [ ] Type hints on all public methods\n"
            f"- [ ] Unit tests cover happy path and failure mode\n"
        )

        return Skill(
            name=safe_name,
            description=agent_spec.responsibility,
            trigger_keywords=[safe_name, agent_spec.name.lower(), architecture.pattern],
            content=content,
            category="agent",
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Extract JSON from potentially markdown-fenced LLM output."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
            if "```" in cleaned:
                cleaned = cleaned[: cleaned.rindex("```")]
            cleaned = cleaned.strip()
        return json.loads(cleaned)
