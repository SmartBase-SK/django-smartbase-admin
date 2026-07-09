import {SBAdminTableModule} from "./base_module"


export class DataEditModule extends SBAdminTableModule {

    modifyTabulatorOptions(tabulatorOptions) {
        // A column may declare `sbadminPerCellEditableField` — the name of a per-row boolean field in
        // the row data. Turn it into a Tabulator `editable` callback so editability can vary
        // per cell (e.g. a delta column that is read-only on rows not using that component).
        (tabulatorOptions.columns || []).forEach((column) => {
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
