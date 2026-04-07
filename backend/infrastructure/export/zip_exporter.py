"""Infrastructure adapter: ZIP file exporter."""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from core.ports.file_exporter import IFileExporter

logger = logging.getLogger(__name__)


class ZipExporter(IFileExporter):
    """Exports generated files as in-memory ZIP archives or to disk."""

    async def export_zip(
        self,
        files: dict[str, str],
        project_name: str,
    ) -> bytes:
        """Create an in-memory ZIP archive containing all ``files``.

        Args:
            files: Mapping of ``filename -> content`` (e.g.
                ``{"src/main.py": "print('hello')"}``)
            project_name: Used as the top-level directory inside the ZIP.

        Returns:
            Raw bytes of the ZIP archive, ready for HTTP response or disk write.
        """
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, content in files.items():
                arcname = f"{project_name}/{filename}"
                zf.writestr(arcname, content)
                logger.debug("Added to ZIP: %s", arcname)

        zip_bytes = buffer.getvalue()
        logger.info(
            "Created ZIP for project '%s': %d files, %d bytes",
            project_name,
            len(files),
            len(zip_bytes),
        )
        return zip_bytes

    async def export_skill(
        self,
        skill_content: str,
        skill_name: str,
        output_dir: str,
    ) -> str:
        """Write a Claude Code SKILL.md file to the given directory.

        Args:
            skill_content: The full Markdown content for the skill.
            skill_name: Directory name for the skill (e.g. ``T001-auth-setup``).
            output_dir: Parent directory where the skill folder is created.

        Returns:
            Absolute path to the written SKILL.md file.
        """
        skill_dir = Path(output_dir) / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(skill_content, encoding="utf-8")

        resolved = str(skill_path.resolve())
        logger.info("Exported skill '%s' to %s", skill_name, resolved)
        return resolved
