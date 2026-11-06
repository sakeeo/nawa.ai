import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from nawa.core.errors import NotFoundError

DEFAULT_PROMPTS_DIR = Path(__file__).parent / "prompts"
_FILE = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d+)\.yaml$")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    template: str

    def render(self, **values: str) -> str:
        return self.template.format(**values)


class PromptRegistry:
    """Loads prompts from versioned YAML files named <name>.v<version>.yaml."""

    def __init__(self, directory: Path = DEFAULT_PROMPTS_DIR) -> None:
        self._dir = directory

    def get(self, name: str, version: int | None = None) -> Prompt:
        versions: dict[int, Path] = {}
        for path in self._dir.glob(f"{name}.v*.yaml"):
            match = _FILE.match(path.name)
            if match and match["name"] == name:
                versions[int(match["version"])] = path
        if not versions:
            raise NotFoundError(f"Prompt '{name}' not found")
        chosen = version if version is not None else max(versions)
        if chosen not in versions:
            raise NotFoundError(f"Prompt '{name}' version {chosen} not found")
        path = versions[chosen]
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data.get("name") != name or data.get("version") != chosen:
            raise ValueError(f"{path.name}: header name/version does not match the file name")
        return Prompt(name=name, version=chosen, template=str(data["template"]))
