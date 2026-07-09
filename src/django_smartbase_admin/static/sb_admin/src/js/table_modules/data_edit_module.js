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
            const row = cell.getRow()
            const currentRowId = row.getData()[this.table.tableIdColumnName]
            const editRequestData = new FormData()
            editRequestData.set('currentRowId', currentRowId)
            editRequestData.set('columnFieldName', cell.getColumn().getField())
            editRequestData.set('cellValue', cell.getValue())
            window.htmx.ajax('POST', this.table.tableDataEditUrl, {
                'swap': 'none',
                'values': {
                    'currentRowId': currentRowId,
                    'columnFieldName': cell.getColumn().getField(),
                    'cellValue': cell.getValue()
                }
            })
        })
    }
}
