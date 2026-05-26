from django import template

from django_smartbase_admin.engine.const import PAGINATION_ACTIVE_RANGE

register = template.Library()


def build_tabulator_style_page_items(
    current_page: int,
    max_page: int,
    active_range: int = PAGINATION_ACTIVE_RANGE,
) -> list[dict]:
    """Build page button items matching Tabulator list pagination (table_params_module)."""
    if max_page <= 1:
        return []

    if max_page <= active_range + 1:
        return [
            {"kind": "page", "number": page_num, "active": page_num == current_page}
            for page_num in range(1, max_page + 1)
        ]

    items: list[dict] = []
    half = active_range // 2

    def add_page(page_num: int) -> None:
        items.append(
            {"kind": "page", "number": page_num, "active": page_num == current_page}
        )

    def add_ellipsis() -> None:
        items.append({"kind": "ellipsis"})

    if current_page < active_range:
        for page_num in range(1, active_range + 1):
            add_page(page_num)
        add_ellipsis()
        add_page(max_page)
    else:
        add_page(1)
        add_ellipsis()
        if current_page > max_page - active_range + 1:
            for page_num in range(max_page - active_range + 1, max_page + 1):
                add_page(page_num)
        else:
            start = current_page - half
            for page_num in range(start, start + active_range):
                add_page(page_num)
            add_ellipsis()
            add_page(max_page)

    return items


@register.simple_tag
def tabulator_style_inline_pages(page_obj):
    return build_tabulator_style_page_items(
        current_page=page_obj.number,
        max_page=page_obj.paginator.num_pages,
    )
