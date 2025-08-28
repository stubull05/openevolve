# openevolve/prompt/templates.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional

@dataclass
class Template:
    name: str
    text: str

def _normalize_placeholders(text: str) -> str:
    """
    Convert Jinja-style placeholders {{ name }} to Python str.format placeholders {name}.
    Leaves anything already like {name} untouched.
    """
    import re
    return re.sub(r"\{\{\s*([a-zA-Z0-9_\.]+)\s*\}\}", r"{\1}", text)

class TemplateManager:
    def __init__(self, template_dir: Optional[str] = None) -> None:
        # Built-ins that match PromptSampler's usage (.format-based placeholders)
        self.templates: Dict[str, Template] = {
            # user prompts
            "diff_user": Template(
                "diff_user",
                (
                    "You are an expert software engineer. Improve the current program by proposing a focused diff.\n"
                    "### Fitness\n{metrics}\n\n"
                    "Overall fitness: {fitness_score}\nFeature space: {feature_coords}\nDimensions: {feature_dimensions}\n\n"
                    "### Improvement Areas\n{improvement_areas}\n\n"
                    "### Evolution History\n{evolution_history}\n\n"
                    "{artifacts}\n"
                    "Return ONLY code edits using one of the supported diff formats."
                )
            ),
            "full_rewrite_user": Template(
                "full_rewrite_user",
                (
                    "You are an expert software engineer. Produce a clean, full rewrite of the program in {language}.\n"
                    "### Fitness\n{metrics}\n\n"
                    "Overall fitness: {fitness_score}\nFeature space: {feature_coords}\nDimensions: {feature_dimensions}\n\n"
                    "### Improvement Areas\n{improvement_areas}\n\n"
                    "### Evolution History\n{evolution_history}\n\n"
                    "{artifacts}\n"
                    "Return ONLY the new source code."
                )
            ),

            # history/blocks
            "evolution_history": Template(
                "evolution_history",
                (
                    "# Program Evolution History\n\n"
                    "## Previous Attempts\n{previous_attempts}\n\n"
                    "## Top Programs\n{top_programs}\n\n"
                    "{inspirations_section}\n"
                )
            ),
            "previous_attempt": Template(
                "previous_attempt",
                (
                    "- Attempt #{attempt_number}\n"
                    "  - Changes: {changes}\n"
                    "  - Performance: {performance}\n"
                    "  - Outcome: {outcome}\n"
                )
            ),
            "top_program": Template(
                "top_program",
                (
                    "### Program {program_number}\n"
                    "- Score: {score}\n"
                    "- Language: {language}\n"
                    "- Key features: {key_features}\n"
                    "```{language}\n{program_snippet}\n```\n"
                )
            ),
            "inspirations_section": Template(
                "inspirations_section",
                "## Inspirations\n{inspiration_programs}\n"
            ),
            "inspiration_program": Template(
                "inspiration_program",
                (
                    "### Inspiration {program_number} ({program_type})\n"
                    "- Score: {score}\n"
                    "- Unique features: {unique_features}\n"
                    "```{language}\n{program_snippet}\n```\n"
                )
            ),

            # fragments (used with .format(...) later by sampler)
            "fitness_stable": Template("fitness_stable", "Fitness unchanged at {current}"),
            "fitness_improved": Template("fitness_improved", "Fitness improved from {prev} to {current}"),
            "fitness_declined": Template("fitness_declined", "Fitness declined from {prev} to {current}"),
            "exploring_region": Template("exploring_region", "Exploring feature region: {features}"),
            "code_too_long": Template("code_too_long", "Code length exceeds threshold ({threshold} chars). Consider simplifying."),
            "no_specific_guidance": Template("no_specific_guidance", "No specific issues detected; explore alternative implementations or optimizations.")
        }

        # Overlay with disk templates if a directory is provided
        if template_dir:
            self._load_from_directory(Path(template_dir))

    def _load_from_directory(self, root: Path) -> None:
        if not root.exists() or not root.is_dir():
            return
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".jinja", ".j2", ".txt", ".md", ".template"}:
                continue
            name = p.stem  # filename without extension
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            text = _normalize_placeholders(text)
            self.templates[name] = Template(name, text)

    def get_template(self, name: str) -> str:
        t = self.templates.get(name)
        if not t:
            raise ValueError(f"Template '{name}' not found")
        return t.text

    def get_fragment(self, name: str, **_: Any) -> str:
        # Keep signature flexible; return raw (normalized) fragment text.
        t = self.templates.get(name)
        if not t:
            raise ValueError(f"Fragment '{name}' not found")
        return t.text
