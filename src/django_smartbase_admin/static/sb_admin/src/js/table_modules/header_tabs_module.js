import {SBAdminTableModule} from "./base_module"
import {filterInputValueChangedUtil} from "../utils"


export class HeaderTabsModule extends SBAdminTableModule {
    afterInit() {
        const filterOptionsWrapper = document.querySelector(".js-filters-options")
        const targetInput = document.querySelector(`[name=${this.table.constants.TABLE_PARAMS_SELECTED_FILTER_TYPE}]`)
        if (!filterOptionsWrapper || !targetInput) {
            return
        }
        filterOptionsWrapper.querySelectorAll('[data-bs-toggle]').forEach(el => {
            el.addEventListener("show.bs.tab", (event) => {
                const targetId = event.target.id
                if (targetId !== 'tab_saved_views') {
                    targetInput.value = event.target.id
                }
            })
        })
    }

    beforeRefreshTableDataIfNotUrlLoad() {
        const tabs = document.querySelectorAll('.tabulator-custom-header .tab-pane')
        const tabSelectInput = document.querySelector(`[name=${this.table.constants.TABLE_PARAMS_SELECTED_FILTER_TYPE}]`)
        tabs.forEach((tab) => {
            if (tabSelectInput.value !== tab.getAttribute('aria-labelledby')) {
                tab.querySelectorAll(`[form=${this.table.filterFormId}]`).forEach((input) => {
                    if (input !== tabSelectInput) {
                        input.value = ''
                        filterInputValueChangedUtil(input)
                        input.dispatchEvent(new CustomEvent('clearSelectedItems'))
                    }
                })
            }
        })
        if (tabSelectInput.value !== "tab_advanced_filters") {
            const queryBuilder = document.querySelector(`#${this.table.advancedFilterId}`)
            const emptyRules = {
                "condition": "AND",
                "rules": [{empty: true}]
            }
            $(queryBuilder).queryBuilder("setRules", emptyRules)
        }
    }


    loadFromUrlAfterInit() {
        const targetInput = document.querySelector(`[name=${this.table.constants.TABLE_PARAMS_SELECTED_FILTER_TYPE}]`)
        if (!targetInput) {
            return
        }
        if (targetInput.value === "") {
            const filterOptionsWrapper = document.querySelector(".js-filters-options")
            targetInput.value = filterOptionsWrapper.querySelector('[data-bs-toggle="tab"]').id
        }
        const params = this.table.getParamsFromUrl()
        const targetTabValue = params[this.table.constants.FILTER_DATA_NAME]?.[this.table.constants.TABLE_PARAMS_SELECTED_FILTER_TYPE]
        if (targetTabValue) {
            targetInput.value = targetTabValue
        }
        document.getElementById(targetInput.value).click()
    }
}
