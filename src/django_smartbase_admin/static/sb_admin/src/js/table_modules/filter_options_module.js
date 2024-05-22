import { SBAdminTableModule } from "./base_module"


export class FilterOptionsModule extends SBAdminTableModule {
    afterInit() {
        const filterOptionsWrapper = document.querySelector(".js-filters-options")
        const targetInput = document.querySelector(`[name=${this.table.constants.TABLE_PARAMS_SELECTED_FILTER_TYPE}]`)
        if(!filterOptionsWrapper || !targetInput) {
            return
        }
        filterOptionsWrapper.querySelectorAll('[data-bs-toggle]').forEach(el => {
            el.addEventListener("show.bs.tab", (event) => {
                targetInput.value = event.target.id
                targetInput.dispatchEvent(new Event('change'))
            })
        })
    }


    loadFromUrlAfterInit() {
        const targetInput = document.querySelector(`[name=${this.table.constants.TABLE_PARAMS_SELECTED_FILTER_TYPE}]`)
        if (!targetInput) {
            return
        }
        const params = this.table.getParamsFromUrl()
        const targetTabValue = params[this.table.constants.FILTER_DATA_NAME]?.[this.table.constants.TABLE_PARAMS_SELECTED_FILTER_TYPE]
        if (targetTabValue) {
            targetInput.value = targetTabValue
        }
        document.getElementById(targetInput.value).click()
    }
}
