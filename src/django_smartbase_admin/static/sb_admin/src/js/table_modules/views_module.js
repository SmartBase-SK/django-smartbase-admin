import {SBAdminTableModule} from "./base_module"

export class ViewsModule extends SBAdminTableModule {
    requiresHeader() {
        return true
    }

    refreshViewButtons() {
        const urlParamsString = this.table.getUrlParamsStringForSave()
        const searchParams = decodeURI(urlParamsString)
        const selectedParams = JSON.stringify(this.selectedViewParams)
        const saveButton = document.getElementById('save-view-modal-button')
        let selectedView = null
        if (saveButton) {
            saveButton.disabled = true
        }

        document.querySelectorAll('.js-view-button').forEach((item) => {
            const itemParams = JSON.stringify(JSON.parse(item.dataset.params))
            const sameAsUrlParams = (itemParams === searchParams)
            const sameAsSelectedParams = selectedParams === itemParams
            item.classList.remove("active")
            item.classList.remove("changed")

            if (!this.selectedViewParams && sameAsUrlParams) {
                item.classList.add("active")
                selectedView = item
                this.selectedViewParams = JSON.parse(item.dataset.params)
            }
            if (sameAsSelectedParams) {
                selectedView = item
                item.classList.add("active")
            }
            if (sameAsSelectedParams && !sameAsUrlParams && this.selectedViewParams) {
                if (saveButton) {
                    saveButton.disabled = false
                }
                item.classList.add("changed")
            }
        })
        if (!selectedView) {
            if (saveButton) {
                saveButton.disabled = false
            }
        }
        document.querySelector("#" + this.table.constants.URL_PARAMS_NAME).value = searchParams
    }

    afterUrlStateUpdate() {
        this.refreshViewButtons()
    }

    loadFromUrlAfterInit() {
        this.refreshViewButtons()
    }

    openView(e, params) {
        if(e.target.closest('svg')){
            return
        }
        const savedParams = JSON.parse(params) || {}
        const allParams = this.table.getAllUrlParams()
        this.selectedViewParams = savedParams
        allParams[this.table.viewId] = savedParams
        history.pushState({}, '', window.location.pathname + this.table.paramsObjectToUrlString(allParams))
        this.table.loadFromUrl()
    }
}
