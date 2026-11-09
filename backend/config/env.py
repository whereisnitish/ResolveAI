import os


def configure_settings_module() -> None:
    """Point DJANGO_SETTINGS_MODULE at config.settings.<DJANGO_ENV> (default: dev)."""
    django_env = os.environ.get("DJANGO_ENV", "dev")
    if django_env not in {"dev", "test", "prod"}:
        raise RuntimeError(f"Unsupported DJANGO_ENV={django_env!r}")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"config.settings.{django_env}")
