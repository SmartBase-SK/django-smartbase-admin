import {SBAdminTableModule} from "./base_module"


export class DetailViewModule extends SBAdminTableModule {

    afterInit() {
        this.table.tabulator.on("rowClick", (e, row) => {
            if (e.target.closest(".row-select-wrapper") || e.target.closest(".row-prevent-click")) {
                return
            }
            window.location = this.table.tableDetailUrl.replace(this.table.constants.OBJECT_ID_PLACEHOLDER, row.getData()[this.table.tableIdColumnName]) + '?_changelist_filters=' + encodeURIComponent(this.table.getUrlParamsString().replace('?' + this.table.constants.BASE_PARAMS_NAME + '=', '' + this.table.constants.BASE_PARAMS_NAME + '='))
        })
    }
}
