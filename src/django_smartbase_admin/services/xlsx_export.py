import io
import re
from copy import copy

import xlsxwriter
from django.http import HttpResponse
from django.utils.encoding import smart_str
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy

from django_smartbase_admin.engine.const import Formatter
from django_smartbase_admin.utils import JSONSerializableMixin


class SBAdminXLSXExportService(object):
    @classmethod
    def write_workbook(cls, export_file, data, columns, options=None):
        options = options or {}
        workbook = xlsxwriter.Workbook(
            export_file, {"in_memory": True, "remove_timezone": True}
        )
        worksheet = workbook.add_worksheet()

        worksheet.set_default_row(options.get("default_row_height", 15))
        worksheet.add_write_handler(type(gettext_lazy("")), cls.write_proxy)
        header_rows_count = options.get("header_rows_count", 0)
        header_rows_height = options.get("header_rows_height", 25)
        header_rows_freeze = options.get("header_rows_freeze", True)
        default_cell_format_options = options.get("cell_format", {})
        header_cell_format_options = options.get("header_cell_format", {})
        cell_format_options = options.get("cell_formats", {})
        conditional_format_options = options.get("conditional_formats", {})
        default_cell_format = workbook.add_format(default_cell_format_options)
        header_cell_format = workbook.add_format(header_cell_format_options)

        cell_formats_dict = {}
        for cell_format_key, cell_format in cell_format_options.items():
            cell_formats_dict[cell_format_key] = workbook.add_format(cell_format)
        for (
            conditional_format_range,
            conditional_format,
        ) in conditional_format_options.items():
            cond_format = copy(conditional_format)
            cond_format["format"] = cell_formats_dict[cond_format["format"]]
            worksheet.conditional_format(conditional_format_range, cond_format)

        for row in range(header_rows_count):
            worksheet.set_row(row, header_rows_height)
        if header_rows_freeze and header_rows_count > 0:
            worksheet.freeze_panes(header_rows_count, 0)
        if header_rows_count > 0:
            for col, column in enumerate(columns):
                column_to_write = column.get("title", "")
                column_to_write = (
                    str(column_to_write) if column_to_write else column_to_write
                )
                worksheet.write(
                    0,
                    col,
                    column_to_write,
                    header_cell_format,
                )
        row = 0 + header_rows_count
        col = 0
        for data_row in data:
            for column in columns:
                data_col = data_row.get(column["field"], "")
                column_formatter = column.get("formatter", None)
                image_write = False
                if column_formatter == Formatter.IMAGE.value:
                    if row >= header_rows_count:
                        try:
                            worksheet.write_formula(
                                row,
                                col,
                                f'=_xlfn.IMAGE("{data_col}")',
                                cell_format=default_cell_format,
                            )
                            image_write = True
                        except ValueError:
                            pass
                if column_formatter == Formatter.HTML.value:
                    # replace all possible variants of <br> with new line
                    data_col = re.sub(r"<br\s*/?>", "\n", str(data_col))
                    data_col = strip_tags(data_col).strip()
                if not image_write:
                    worksheet.write(
                        row,
                        col,
                        data_col,
                        (
                            default_cell_format
                            if row >= header_rows_count
                            else header_cell_format
                        ),
                    )
                col += 1
            row += 1
            col = 0

        worksheet.autofit()
        workbook.close()

    @classmethod
    def write_proxy(cls, worksheet, row, col, proxy_value, format=None):
        return worksheet.write_string(row, col, str(proxy_value), format)

    @classmethod
    def create_workbook_http_respone(cls, file_name, data, columns, options=None):
        export_file = io.BytesIO()
        cls.write_workbook(export_file, data, columns, options)
        response = HttpResponse(
            export_file.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f"attachment; filename={smart_str(file_name)}"
        response["Content-Length"] = export_file.tell()
        return response


class SBAdminXLSXOptions(JSONSerializableMixin):
    header_cell_format: "SBAdminXLSXFormat" = None
    cell_format: "SBAdminXLSXFormat" = None
    default_row_height = None
    header_rows_count = None
    header_rows_height = None
    header_rows_freeze = None

    def __init__(
        self,
        header_cell_format=None,
        cell_format=None,
        default_row_height=None,
        header_rows_count=None,
        header_rows_height=None,
        header_rows_freeze=None,
    ) -> None:
        super().__init__()
        self.header_cell_format = header_cell_format
        self.cell_format = cell_format
        self.default_row_height = default_row_height
        self.header_rows_count = header_rows_count
        self.header_rows_height = header_rows_height
        self.header_rows_freeze = header_rows_freeze

    def to_json(self):
        return {
            k: v.to_json() if isinstance(v, JSONSerializableMixin) else v
            for k, v in self.__dict__.items()
            if v
        }


class SBAdminXLSXFormat(JSONSerializableMixin):
    # Font type
    font_name = None
    # Font size
    font_size = None
    # Font color
    font_color = None
    # Bold
    bold = None
    # Italic
    italic = None
    # Underline
    underline = None
    # Strikeout
    font_strikeout = None
    # Super/Subscript
    font_script = None
    # Numeric format
    num_format = None
    # Lock cells
    locked = None
    # Hide formulas
    hidden = None
    # Horizontal align
    align = None
    # Vertical align
    valign = None
    # Rotation
    rotation = None
    # Text wrap
    text_wrap = None
    # Reading order
    reading_order = None
    # Justify last
    text_justlast = None
    # Center across
    center_across = None
    # Indentation
    indent = None
    # Shrink to fit
    shrink = None
    # Cell pattern
    pattern = None
    # Background color
    bg_color = None
    # Foreground color
    fg_color = None
    # Cell border
    border = None
    # Bottom border
    bottom = None
    # Top border
    top = None
    # Left border
    left = None
    # Right border
    right = None
    # Border color
    border_color = None
    # Bottom color
    bottom_color = None
    # Top color
    top_color = None
    # Left color
    left_color = None
    # Right color
    right_color = None

    def __init__(
        self,
        font_name=None,
        font_size=None,
        font_color=None,
        bold=None,
        italic=None,
        underline=None,
        font_strikeout=None,
        font_script=None,
        num_format=None,
        locked=None,
        hidden=None,
        align=None,
        valign=None,
        rotation=None,
        text_wrap=None,
        reading_order=None,
        text_justlast=None,
        center_across=None,
        indent=None,
        shrink=None,
        pattern=None,
        bg_color=None,
        fg_color=None,
        border=None,
        bottom=None,
        top=None,
        left=None,
        right=None,
        border_color=None,
        bottom_color=None,
        top_color=None,
        left_color=None,
        right_color=None,
    ) -> None:
        super().__init__()
        self.font_name = font_name
        self.font_size = font_size
        self.font_color = font_color
        self.bold = bold
        self.italic = italic
        self.underline = underline
        self.font_strikeout = font_strikeout
        self.font_script = font_script
        self.num_format = num_format
        self.locked = locked
        self.hidden = hidden
        self.align = align
        self.valign = valign
        self.rotation = rotation
        self.text_wrap = text_wrap
        self.reading_order = reading_order
        self.text_justlast = text_justlast
        self.center_across = center_across
        self.indent = indent
        self.shrink = shrink
        self.pattern = pattern
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.border = border
        self.bottom = bottom
        self.top = top
        self.left = left
        self.right = right
        self.border_color = border_color
        self.bottom_color = bottom_color
        self.top_color = top_color
        self.left_color = left_color
        self.right_color = right_color
