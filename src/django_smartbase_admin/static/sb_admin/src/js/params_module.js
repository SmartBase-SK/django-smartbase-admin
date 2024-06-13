import { Module } from "tabulator-tables"

export class AjaxParamsTabulatorModifier extends Module {
    static moduleName = "sb_ajax_params_tabulator_modifier"

    constructor(table) {
        super(table)
    }

    initialize() {
        if (this.table.SBTable) {
            this.subscribe("data-params", (data, config, silent, params) => {
                this.table.SBTable.lastTableParams = params
                if (this.table.SBTable.tabulatorOptions["ajaxConfig"]["method"] === "POST") {
                    return this.table.SBTable.getAllUrlParams()
                }
                return {}
            }, 10001)
        }
    }
}
