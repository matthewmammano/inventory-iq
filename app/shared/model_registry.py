"""Import ORM model modules so SQLAlchemy metadata is complete."""

from importlib import import_module

MODEL_MODULES = (
    "app.alerts.models",
    "app.auth.models",
    "app.inventory.models",
    "app.prediction.models",
    "app.shared.models",
)


def import_model_modules() -> None:
    for module_name in MODEL_MODULES:
        import_module(module_name)
