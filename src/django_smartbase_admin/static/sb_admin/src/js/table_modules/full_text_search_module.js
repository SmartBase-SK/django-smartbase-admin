import { SBAdminTableModule } from "./base_module"


export class FullTextSearchModule extends SBAdminTableModule {
    loadFromUrl() {
        this.searchInputEl = document.getElementById(`id_${this.table.constants.TABLE_PARAMS_FULL_TEXT_SEARCH}`)
        if(!this.searchInputEl) {
            return
        }
        const params = this.table.getParamsFromUrl()
        const searchValue = params[this.table.constants.FILTER_DATA_NAME]?.[this.table.constants.TABLE_PARAMS_FULL_TEXT_SEARCH]
        this.searchInputEl.value = searchValue || ""
    }
}
