import {SBAdminTableModule} from "./base_module"


export class DataEditModule extends SBAdminTableModule {

    afterInit() {
        this.table.tabulator.on("cellEdited", (cell) => {
            const row = cell.getRow()
            const currentRowId = row.getData()[this.table.tableIdColumnName]
            const editRequestData = new FormData()
            editRequestData.set('currentRowId', currentRowId)
            editRequestData.set('columnFieldName', cell.getColumn().getField())
            editRequestData.set('cellValue', cell.getValue())
            fetch(this.table.tableDataEditUrl, {
                method: 'POST',
                headers: {
                    "X-CSRFToken": window.csrf_token,
                },
                body: editRequestData
            }).then(response => response.json())
                .then(res => {
                    console.log(res)
                })
        })
    }
}
