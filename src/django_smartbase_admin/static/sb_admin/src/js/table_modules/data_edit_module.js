import {TabulatorFull as Tabulator} from "tabulator-tables"
import {SBAdminTableModule} from "./base_module"


// Numeric text editor that tolerates a formatted value (leading "+"/"-" and a locale decimal
// comma), unlike the built-in "number" editor which blanks such values on focus. It edits the
// value as text; the server is expected to parse it back.
function sbadminDecimalInputEditor(cell, onRendered, success, cancel) {
    const input = document.createElement("input")
    input.type = "text"
    input.setAttribute("inputmode", "decimal")
    input.style.cssText = "width:100%;box-sizing:border-box;padding:4px"
    const current = cell.getValue()
    const original = (current === null || current === undefined) ? "" : String(current)
    input.value = original.trim()
    onRendered(() => {
        input.focus()
        input.select()
    })
    // Only commit a real change — otherwise focus/blur with no edit would "change" the value
    // (e.g. the formatted value has a trailing space) and trigger a save.
    const commit = () => {
        const value = input.value.trim()
        if (value === original.trim()) {
            cancel()
        } else {
            success(value)
        }
    }
    input.addEventListener("blur", commit)
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            commit()
        } else if (event.key === "Escape") {
            cancel()
        }
    })
    // Allow only sign, digits and decimal separators (comma/dot).
    input.addEventListener("input", () => {
        const cleaned = input.value.replace(/[^0-9+,.-]/g, "")
        if (cleaned !== input.value) {
            input.value = cleaned
        }
    })
    return input
}


export class DataEditModule extends SBAdminTableModule {

    modifyTabulatorOptions(tabulatorOptions) {
        // Register the custom editor before the table is built (columns resolve their editor by
        // name at build time). Only tables with the data-edit module get it.
        Tabulator.extendModule("edit", "editors", {sbadminDecimalInput: sbadminDecimalInputEditor})
        // A column may declare `sbadminPerCellEditableField` — the name of a per-row boolean field
        // in the row data. Turn it into a Tabulator `editable` callback so editability can vary
        // per cell (e.g. a delta column that is read-only on rows not using that component).
        const columns = tabulatorOptions.columns || []
        columns.forEach((column) => {
            const perCellEditableField = column.sbadminPerCellEditableField
            if (perCellEditableField) {
                column.editable = (cell) => Boolean(cell.getRow().getData()[perCellEditableField])
            }
        })
        return tabulatorOptions
    }

    afterInit() {
        this.table.tabulator.on("cellEdited", (cell) => {
            const currentRowId = cell.getRow().getData()[this.table.tableIdColumnName]
            const field = cell.getColumn().getField()
            const value = cell.getValue()
            const request = window.htmx.ajax('POST', this.table.tableDataEditUrl, {
                'swap': 'none',
                'values': {
                    'currentRowId': currentRowId,
                    'columnFieldName': field,
                    'cellValue': value
                }
            })
            Promise.resolve(request).then(() => {
                document.dispatchEvent(new CustomEvent(window.sb_admin_const.TABLE_CELL_EDITED_EVENT_NAME, {
                    detail: {table: this.table, rowId: currentRowId, field: field, value: value}
                }))
            })
        })
    }
}
