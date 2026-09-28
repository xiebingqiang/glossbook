"""`init` (config templates) and `models` (list configured models)."""
import os
from pathlib import Path

from . import config


def cmd_models(args):
    models, default = config.load_models()
    for name, m in models.items():
        key = "set" if os.environ.get(m["key_env"]) else "missing"
        p = m.get("price", {})
        print(f"{'*' if name == default else ' '} {name:<12} {m['model']:<28} {m['key_env']} {key:<8} "
              f"input {p.get('input', '?')} / cached {p.get('input_cached', '?')} / output {p.get('output', '?')} "
              "USD per 1M tokens")


ENV_TEMPLATE = """# glossbook API keys (keys only; models are defined in models.toml)
DEEPSEEK_API_KEY=
# OPENROUTER_API_KEY=
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
# GEMINI_API_KEY=
# Default model (optional; overrides `default` in models.toml)
# GLOSSBOOK_MODEL=ds4pro
"""
SETTINGS_TEMPLATE = """# glossbook defaults. Set only what you want to change; the rest follows the level preset.
# Command-line flags take precedence.
[settings]
target = "{target}"
level = "B1"
# density = "normal"   # low / normal / high / words per ruby
# per_note = "clause"  # clause / 1 / 2 / 3 / para
# culture = true
# intro = true
# translation = true
# jobs = 8
"""


def cmd_init(args):
    """Default: ~/.config/glossbook/{.env,config.toml}, found from any directory. --here: ./.env and
    ./glossbook.toml (they take precedence over the global files when you run glossbook here)."""
    if args.here:
        env, settings = Path(".env"), Path("glossbook.toml")
    else:
        config.USER_DIR.mkdir(parents=True, exist_ok=True)
        env, settings = config.USER_DIR / ".env", config.USER_DIR / "config.toml"
    for p, text in ((env, ENV_TEMPLATE), (settings, SETTINGS_TEMPLATE.replace("{target}", args.target))):
        if p.exists():
            print(f"Exists, skipped: {p}")
            continue
        p.write_text(text, encoding="utf-8")
        if p == env:
            p.chmod(0o600)
        print(f"Wrote {p}")
    print(f"Next: put your API key in {env} (DEEPSEEK_API_KEY for the default model), then check it with "
          "`glossbook models`.\n"
          f"To customize models, copy {config.PKG_DIR / 'models.toml'} to {config.USER_DIR / 'models.toml'} "
          "or ./models.toml and edit it.")
