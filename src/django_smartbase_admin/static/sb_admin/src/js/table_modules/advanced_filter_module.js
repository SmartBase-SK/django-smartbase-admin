import { SBAdminTableModule } from "./base_module"
import { filterInputValueChangedUtil, filterInputValueChangeListener } from "../utils"

export class AdvancedFilterModule extends SBAdminTableModule {
    afterInit() {
        document.querySelector("[data-execute]").addEventListener("click", () => {
            this.table.refreshTableDataIfNotUrlLoad()

        })
    }

    initFilters(target) {
        target.querySelectorAll(`[form=${this.table.advancedFilterId}]`).forEach(el => {
            filterInputValueChangedUtil(el)
        })
        filterInputValueChangeListener(`[form=${this.table.advancedFilterId}]`, (event) => {
            filterInputValueChangedUtil(event.target)
        })
    }

    getUrlParams() {
        const queryBuilder = document.querySelector(`#${this.table.advancedFilterId}`)
        return {
            "advancedFilterData": $(queryBuilder).queryBuilder("getRules")
        }
    }
}
