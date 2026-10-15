import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = Path("data")
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:14b-instruct"
    claude_model: str = "claude-sonnet-5-5"


def load_settings(config_file: Path) -> Settings:
    if not config_file.exists():
        return Settings()
    values = tomllib.loads(config_file.read_text(encoding="utf-8"))
    if "anthropic_api_key" in values:
        raise ConfigError(
            "Put the Claude key in the ANTHROPIC_API_KEY environment variable, "
            "not in the config file."
        )
    known = {f.name for f in fields(Settings)}
    unknown = set(values) - known
    if unknown:
        raise ConfigError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    if "data_dir" in values:
        values["data_dir"] = Path(values["data_dir"])
    return Settings(**values)
