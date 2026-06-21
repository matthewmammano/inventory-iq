"""Small safe-HTML formatting helpers."""

from markupsafe import Markup, escape


def bold_item_name(item_name: object) -> Markup:
    return Markup('<strong class="item-name">') + escape("" if item_name is None else item_name) + Markup("</strong>")
