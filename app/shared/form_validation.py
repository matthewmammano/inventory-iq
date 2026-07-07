"""Frontend validation metadata for form fields backed by Python validators."""

from html import escape
from typing import Any

from app.shared.validation_types import FIELD_SPECS, FieldRuleName


class SafeHtmlAttrs(str):
    """Escaped HTML attribute string for Jinja template insertion."""

    def __html__(self) -> str:
        return self


def validation_attrs(
    rule_name: FieldRuleName | str,
    *,
    pair_with: str | None = None,
    required_when: str | None = None,
    compare_to: str | None = None,
    compare_mode: str | None = None,
    compare_message: str | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
    **overrides: Any,
) -> SafeHtmlAttrs:
    """Render safe HTML attributes for a named field validation rule."""
    rule_key = rule_name if isinstance(rule_name, FieldRuleName) else FieldRuleName(rule_name.upper())
    rule = FIELD_SPECS[rule_key].with_options(**overrides)
    attrs: dict[str, Any] = {
        "data-validate": rule_key.value,
        "data-validators": ",".join(rule.validators),
        "data-error-message": rule.message,
    }
    if rule.input_type:
        attrs["type"] = rule.input_type
    if rule.inputmode:
        attrs["inputmode"] = rule.inputmode
    if rule.pattern:
        attrs["pattern"] = rule.pattern
    if rule.maxlength is not None:
        attrs["maxlength"] = rule.maxlength
        attrs["data-max-length"] = rule.maxlength
    if rule.min_value is not None:
        attrs["min"] = rule.min_value
    if rule.password_min_length is not None:
        attrs["data-password-min-length"] = rule.password_min_length
    if rule.step:
        attrs["step"] = rule.step
    if rule.placeholder:
        attrs["placeholder"] = rule.placeholder
    if rule.required:
        attrs["required"] = True
    if pair_with:
        attrs["data-pair-with"] = pair_with
    if required_when:
        attrs["data-required-when"] = required_when
    if compare_to:
        attrs["data-compare-to"] = compare_to
    if compare_mode:
        attrs["data-compare-mode"] = compare_mode
    if compare_message:
        attrs["data-compare-message"] = compare_message
    if min_date:
        attrs["min"] = min_date
        attrs["data-min-date"] = min_date
    if max_date:
        attrs["max"] = max_date
        attrs["data-max-date"] = max_date
    return SafeHtmlAttrs(" ".join(_html_attr(key, value) for key, value in attrs.items()))


def _html_attr(key: str, value: Any) -> str:
    if value is True:
        return key
    return f'{key}="{escape(str(value), quote=True)}"'
