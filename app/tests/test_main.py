from talkboard import __main__ as launcher


def test_launcher_serves_on_localhost_with_the_configured_port(tmp_path, monkeypatch):
    (tmp_path / "talkboard.toml").write_text(f'port = 9001\ndata_dir = "{tmp_path}/data"\n')
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    launcher.main()

    ((app, kwargs),) = calls
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9001
    assert app.state.settings.data_dir == tmp_path / "data"


def test_launcher_without_a_config_file_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))

    launcher.main()

    assert calls == [{"host": "127.0.0.1", "port": 8765}]


def test_launcher_wires_the_whisper_model_from_the_config(tmp_path, monkeypatch):
    (tmp_path / "talkboard.toml").write_text(f'whisper_model = "custom/whisper"\ndata_dir = "{tmp_path}/data"\n')
    monkeypatch.chdir(tmp_path)
    apps = []
    monkeypatch.setattr(launcher.uvicorn, "run", lambda app, **kwargs: apps.append(app))

    launcher.main()

    transcriber = apps[0].state.runner.transcriber
    assert transcriber.model == "custom/whisper"
