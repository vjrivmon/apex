"""Sprint 15 S15.5 — tests para el subagent apex-advisor en lib/roles.py."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import roles  # noqa: E402


class TestAdvisorRegistry:
    def test_advisor_in_roles_registry(self):
        assert "apex-advisor" in roles.ROLES

    def test_advisor_uses_opus_and_yellow(self):
        spec = roles.ROLES["apex-advisor"]
        assert spec.model == "opus"
        assert spec.color == "yellow"

    def test_advisor_tools_whitelist_restricted(self):
        """Sólo lectura del context + record_advice. NO Edit/Bash/Task/Read."""
        spec = roles.ROLES["apex-advisor"]
        forbidden = {"Edit", "Write", "Bash", "Task", "Read", "Grep", "Glob"}
        intersection = set(spec.tools) & forbidden
        assert not intersection, (
            f"advisor tiene tools prohibidos: {intersection}"
        )
        assert "mcp__apex__apex_record_advice" in spec.tools

    def test_advisor_install_writes_md(self, tmp_path):
        path, status = roles.install_role("apex-advisor", agents_root=tmp_path)
        assert path.exists()
        assert status in {"written", "overwritten"}
        content = path.read_text(encoding="utf-8")
        assert "name: apex-advisor" in content
        assert "model: opus" in content
        assert "color: yellow" in content
