"""Settings: .env (API keys), models.toml (models), glossbook.toml (defaults), level presets and
command-line flags, merged by priority."""
import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
USER_DIR = Path.home() / ".config" / "glossbook"
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
PER_NOTE = ["clause", "1", "2", "3", "para"]
DENSITY_NAMES = {"low": 2.0, "normal": 1.0, "high": 0.5}  # multiplies the preset "words per ruby"

# Level presets: the higher the level, the more sentences per ¶ and the sparser the rubies.
PRESETS = {
    "A1": {"per_note": "clause", "max_words": 15, "density": 7},
    "A2": {"per_note": "clause", "max_words": 20, "density": 9},
    "B1": {"per_note": "clause", "max_words": 25, "density": 12},
    "B2": {"per_note": "1", "max_words": 35, "density": 20},
    "C1": {"per_note": "2", "max_words": 50, "density": 35},
    "C2": {"per_note": "3", "max_words": 60, "density": 60},
}
DEFAULTS = {"target": "en", "source": None, "level": "B1", "model": None, "jobs": 8,
            "culture": True, "intro": True, "translation": True, "repeat": 3, "max_cost": None, "chunk_words": 300}

# Settings that change what the model outputs (part of the cache key). The rest only affect
# which glosses get a ruby at build time.
GEN_KEYS = ("model", "source", "target", "level", "per_note", "max_words", "culture", "intro", "translation",
            "chunk_words")


@dataclass
class Settings:
    target: str = "en"
    source: str | None = None
    level: str = "B1"
    per_note: str = "clause"
    max_words: int = 25
    density: float = 12        # at most one ruby per this many words, on average
    repeat: int = 3            # at most this many rubies per lemma
    culture: bool = True
    intro: bool = True
    translation: bool = True   # off: the ¶ note has only the glosses and cultural notes
    model: str | None = None
    jobs: int = 8
    max_cost: float | None = None
    chunk_words: int = 300

    def gen(self):
        return {k: getattr(self, k) for k in GEN_KEYS}

    def to_dict(self):
        return asdict(self)


class ConfigError(Exception):
    pass


def load_env(paths=None):
    """Parse KEY=VALUE lines. Variables already set in the environment win."""
    paths = paths or [Path.cwd() / ".env", USER_DIR / ".env"]
    for p in paths:
        if not Path(p).is_file():
            continue
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.removeprefix("export ").split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def _read_toml(p):
    try:
        return tomllib.loads(Path(p).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{p}: invalid TOML: {e}") from e


def load_models(extra_paths=()):
    """Return (models, default). Later files replace same-named models entirely."""
    paths = [PKG_DIR / "models.toml", USER_DIR / "models.toml", Path.cwd() / "models.toml", *extra_paths]
    models, default = {}, None
    for p in paths:
        if Path(p).is_file():
            data = _read_toml(p)
            models.update(data.get("models", {}))
            default = data.get("default", default)
    default = os.environ.get("GLOSSBOOK_MODEL") or default
    for name, m in models.items():
        missing = [k for k in ("base_url", "model", "key_env") if k not in m]
        if missing:
            raise ConfigError(f"model {name!r} is missing {', '.join(missing)}")
        currency = str(m.get("price", {}).get("currency", "USD")).upper()
        if currency != "USD":
            raise ConfigError(f"model {name!r}: prices must be in USD (per million tokens), not {currency}")
    return models, default


def file_settings():
    for p in (Path.cwd() / "glossbook.toml", USER_DIR / "config.toml"):
        if p.is_file():
            return _read_toml(p).get("settings", {})
    return {}


def parse_density(v, preset_value):
    if isinstance(v, int | float):
        return float(v)
    v = str(v).strip().lower()
    if v in DENSITY_NAMES:
        return preset_value * DENSITY_NAMES[v]
    try:
        return float(v)
    except ValueError:
        raise ConfigError(f"density must be low/normal/high or a number (words per ruby), not {v!r}") from None


def resolve(cli=None, from_file=None):
    """cli / from_file hold only what the user set explicitly. The level is decided first, then
    defaults < level preset < config file < command line."""
    cli = {k: v for k, v in (cli or {}).items() if v is not None}
    from_file = file_settings() if from_file is None else from_file
    user = {**from_file, **cli}
    level = str(user.get("level", DEFAULTS["level"])).upper()
    if level not in LEVELS:
        raise ConfigError(f"level must be one of {'/'.join(LEVELS)}, not {level!r}")
    preset = PRESETS[level]
    merged = {**DEFAULTS, **preset, **user, "level": level}
    merged["density"] = parse_density(merged["density"], preset["density"])
    merged["per_note"] = str(merged["per_note"]).lower()
    if merged["per_note"] not in PER_NOTE:
        raise ConfigError(f"per_note must be one of {'/'.join(PER_NOTE)}, not {merged['per_note']!r}")
    for k in ("max_words", "repeat", "jobs", "chunk_words"):
        merged[k] = int(merged[k])
        minimum = 0 if k == "repeat" else 1
        if merged[k] < minimum:
            raise ConfigError(f"{k} must be at least {minimum}")
    if merged["density"] <= 0:
        raise ConfigError("density must be greater than 0")
    unknown = set(merged) - set(Settings.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    return Settings(**merged)


def pick_model(name=None):
    models, default = load_models()
    name = name or default
    if not name:
        raise ConfigError("no model given and models.toml has no default")
    if name not in models:
        raise ConfigError(f"unknown model {name!r}; available: {', '.join(models)}")
    m = dict(models[name], name=name)
    m["api_key"] = os.environ.get(m["key_env"])
    return m
