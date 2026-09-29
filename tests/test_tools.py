from pathlib import Path

from career_resume_skill.config import Settings
from career_resume_skill.tools import environment_report, find_libreoffice, find_tectonic


def test_environment_report_is_secret_free(tmp_path: Path) -> None:
    report = environment_report(Settings(api_key="super-secret", output_dir=str(tmp_path)))

    assert report["api"]["deepseek_configured"] is True
    assert "super-secret" not in str(report)
    assert report["output"]["writable"] is True
    assert "pydantic" in report["dependencies"]


def test_project_tectonic_is_discoverable() -> None:
    compiler = find_tectonic()

    assert compiler is None or compiler.lower().endswith("tectonic.exe")


def test_missing_libreoffice_is_represented_as_optional() -> None:
    executable = find_libreoffice()

    assert executable is None or Path(executable).name.casefold() == "soffice.exe"


def test_environment_output_path_is_resolved_at_config_load(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CAREER_SKILL_OUTPUT_DIR", "relative-output")

    settings = Settings.from_env()

    assert settings.output_dir == str((tmp_path / "relative-output").resolve())
