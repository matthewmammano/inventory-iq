"""Frontend validation metadata for form fields backed by Python validators."""

from html import escape
from typing import Any

from app.shared.validation_types import FIELD_SPECS, FieldRuleName, FieldSpec

_SIMPLE_RULE_ATTRS: tuple[tuple[str, str], ...] = (
    ("input_type", "type"),
    ("inputmode", "inputmode"),
    ("pattern", "pattern"),
    ("step", "step"),
    ("placeholder", "placeholder"),
)

# Cross-field template options, distinct from FieldSpec overrides (required, input_type, ...).
_PASSTHROUGH_ATTRS: dict[str, tuple[str, ...]] = {
    "pair_with": ("data-pair-with",),
    "required_when": ("data-required-when",),
    "compare_to": ("data-compare-to",),
    "compare_mode": ("data-compare-mode",),
    "compare_message": ("data-compare-message",),
    "min_date": ("min", "data-min-date"),
    "max_date": ("max", "data-max-date"),
}


class SafeHtmlAttrs(str):
    """Escaped HTML attribute string for Jinja template insertion."""

    def __html__(self) -> str:
        return self


def validation_attrs(rule_name: FieldRuleName | str, **overrides: Any) -> SafeHtmlAttrs:
    """Render safe HTML attributes for a named field validation rule.

    Keyword arguments are either cross-field template options (see
    `_PASSTHROUGH_ATTRS`, e.g. compare_to, min_date) or overrides applied to
    the rule spec itself (e.g. required, input_type, placeholder).
    """
    passthrough = {key: value for key, value in overrides.items() if key in _PASSTHROUGH_ATTRS}
    rule_overrides = {key: value for key, value in overrides.items() if key not in _PASSTHROUGH_ATTRS}
    rule_key = rule_name if isinstance(rule_name, FieldRuleName) else FieldRuleName(rule_name.upper())
    rule = FIELD_SPECS[rule_key].with_options(**rule_overrides)

    attrs: dict[str, Any] = {
        "data-validate": rule_key.value,
        "data-validators": ",".join(rule.validators),
        "data-error-message": rule.message,
    }
    attrs.update(_rule_attrs(rule))
    attrs.update(_passthrough_attrs(passthrough))
    return SafeHtmlAttrs(" ".join(_html_attr(key, value) for key, value in attrs.items()))


def _rule_attrs(rule: FieldSpec) -> dict[str, Any]:
    """Map a resolved field-rule spec's optional fields into HTML attribute key/value pairs."""
    attrs: dict[str, Any] = {}
    for field, attr_name in _SIMPLE_RULE_ATTRS:
        value = getattr(rule, field)
        if value:
            attrs[attr_name] = value
    if rule.maxlength is not None:
        attrs["maxlength"] = rule.maxlength
        attrs["data-max-length"] = rule.maxlength
    if rule.min_value is not None:
        attrs["min"] = rule.min_value
    if rule.password_min_length is not None:
        attrs["data-password-min-length"] = rule.password_min_length
    if rule.required:
        attrs["required"] = True
    return attrs


def _passthrough_attrs(passthrough: dict[str, Any]) -> dict[str, Any]:
    """Expand caller-supplied cross-field options into their HTML attribute names."""
    attrs: dict[str, Any] = {}
    for key, value in passthrough.items():
        if not value:
            continue
        for attr_name in _PASSTHROUGH_ATTRS[key]:
            attrs[attr_name] = value
    return attrs


def validation_group_attrs(group_name: str, label: str, *, invalid_selector: str | None = None) -> SafeHtmlAttrs:
    """Render safe HTML attributes for a required-choice validation group."""
    attrs: dict[str, Any] = {
        "data-validate-group": "required_choice",
        "data-group-name": group_name,
        "data-label": label,
    }
    if invalid_selector:
        attrs["data-invalid-selector"] = invalid_selector
    return SafeHtmlAttrs(" ".join(_html_attr(key, value) for key, value in attrs.items()))


def _html_attr(key: str, value: Any) -> str:
    if value is True:
        return key
    return f'{key}="{escape(str(value), quote=True)}"'
