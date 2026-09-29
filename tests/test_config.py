from career_resume_skill import config


def test_settings_loads_dotenv_with_bom_compatible_encoding(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_load_dotenv(**kwargs: object) -> None:
        captured.update(kwargs)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    monkeypatch.setattr(config, "load_dotenv", fake_load_dotenv)

    settings = config.Settings.from_env()

    assert captured["encoding"] == "utf-8-sig"
    assert settings.has_api_key is True
