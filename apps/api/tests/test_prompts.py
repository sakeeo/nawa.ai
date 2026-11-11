from pathlib import Path

import pytest

from nawa.core.errors import NotFoundError
from nawa.intelligence.prompts import PromptRegistry


def test_loads_latest_version(tmp_path: Path) -> None:
    (tmp_path / "greet.v1.yaml").write_text("name: greet\nversion: 1\ntemplate: Hi {who}\n")
    (tmp_path / "greet.v2.yaml").write_text("name: greet\nversion: 2\ntemplate: Hello {who}\n")
    prompt = PromptRegistry(tmp_path).get("greet")
    assert prompt.version == 2
    assert prompt.render(who="Rina") == "Hello Rina"


def test_loads_pinned_version(tmp_path: Path) -> None:
    (tmp_path / "greet.v1.yaml").write_text("name: greet\nversion: 1\ntemplate: Hi\n")
    (tmp_path / "greet.v2.yaml").write_text("name: greet\nversion: 2\ntemplate: Hello\n")
    assert PromptRegistry(tmp_path).get("greet", version=1).template == "Hi"


def test_mismatched_header_rejected(tmp_path: Path) -> None:
    (tmp_path / "greet.v1.yaml").write_text("name: other\nversion: 1\ntemplate: Hi\n")
    with pytest.raises(ValueError, match=r"greet\.v1\.yaml"):
        PromptRegistry(tmp_path).get("greet")


def test_unknown_prompt_raises(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        PromptRegistry(tmp_path).get("missing")


def test_bundled_ping_prompt_exists() -> None:
    prompt = PromptRegistry().get("ping")
    assert prompt.name == "ping" and prompt.version >= 1


@pytest.mark.parametrize("name", ["answer", "refuse"])
def test_bundled_rag_prompts_load(name: str) -> None:
    prompt = PromptRegistry().get(name, version=1)
    assert prompt.version == 1 and prompt.template.strip()
    prompt.render()  # no unescaped placeholders


def test_sql_prompts_load_and_render_with_their_placeholders() -> None:
    registry = PromptRegistry()
    generate = registry.get("text_to_sql", version=1)
    rendered = generate.render(
        dialect="PostgreSQL",
        today="2025-12-31",
        schema_block="S",
        metrics_block="M",
        dimensions_block="D",
        fewshot_block="",
    )
    assert "2025-12-31" in rendered and '"sql"' in rendered
    repair = registry.get("sql_repair", version=1)
    text = repair.render(previous_sql="SELECT 1", error="boom")
    assert "SELECT 1" in text and "boom" in text


def test_insight_prompt_loads_and_needs_no_placeholders() -> None:
    prompt = PromptRegistry().get("insight", version=1)
    assert prompt.version == 1 and "ONLY numbers" in prompt.render()
