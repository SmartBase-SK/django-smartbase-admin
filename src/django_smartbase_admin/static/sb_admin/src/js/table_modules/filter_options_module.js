import { SBAdminTableModule } from "./base_module"


export class FilterOptionsModule extends SBAdminTableModule {
    constructor(props) {
        super(props)
        const filterOptionsWrapper = document.querySelector(".js-filters-options")
        this.targetInput = document.querySelector("[name=selected_filter_option]")
        if(!filterOptionsWrapper || !this.targetInput) {
            return
        }
        filterOptionsWrapper.querySelectorAll('[data-bs-toggle]').forEach(el => {
            el.addEventListener("show.bs.tab", (event) => {
                this.targetInput.value = event.target.id
                this.targetInput.dispatchEvent(new Event('change'))
            })
        })
    }


    loadFromUrl() {
        if (!this.targetInput) {
            return
        }
        const params = this.table.getParamsFromUrl()
        const targetTabValue = params[this.table.constants.FILTER_DATA_NAME]?.["selected_filter_option"]
        if (targetTabValue) {
            this.targetInput.value = targetTabValue
            document.getElementById(targetTabValue).click()
        }
    }
}
