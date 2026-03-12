import { SBAdminTableModule } from "./base_module"
import { unset } from "lodash"

export class ViewsModule extends SBAdminTableModule {
    COMPARE_IGNORE_KEYS = ['filterData.sb_selected_filter_type']

    requiresHeader() {
        return true
    }

    // Recursively sort object keys for consistent JSON.stringify output
    sortObjectKeys(obj) {
        if (obj === null || typeof obj !== 'object') {
            return obj
        }
        if (Array.isArray(obj)) {
            return obj.map(item => this.sortObjectKeys(item))
        }
        return Object.keys(obj).sort().reduce((sorted, key) => {
            sorted[key] = this.sortObjectKeys(obj[key])
            return sorted
        }, {})
    }

    filterParamsForCompare(params) {
        this.COMPARE_IGNORE_KEYS.forEach(key_to_remove => {
            unset(params, key_to_remove)
        })
        return params
    }

    // Get normalized JSON string for comparison (sorted keys)
    normalizeForCompare(params) {
        return JSON.stringify(this.sortObjectKeys(this.filterParamsForCompare(params)))
    }

    refreshViewButtons() {
        const urlParams = JSON.parse(this.table.getUrlParamsStringForSave())
        const urlParamsNormalized = this.normalizeForCompare(urlParams)
        const searchParams = decodeURI(JSON.stringify(this.filterParamsForCompare(urlParams)))
        let saveButton = document.getElementById('save-view-modal-button')
        this.selectedViewParams = this.table.getAllParamsFromUrl()[this.table.viewId]
        const selectedParamsNormalized = this.normalizeForCompare(this.selectedViewParams)

        let selectedView = null
        if (saveButton) {
            saveButton.disabled = true
        }

        document.querySelectorAll('.js-view-button').forEach((item) => {
            if(!item.dataset.params) {
                return
            }
            const itemParamsNormalized = this.normalizeForCompare(JSON.parse(item.dataset.params))
            // Fast string comparison with sorted keys
            const sameAsUrlParams = (itemParamsNormalized === urlParamsNormalized)
            const sameAsSelectedParams = (selectedParamsNormalized === itemParamsNormalized)
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

    openView(e, params, view_id) {
        if (!params) {
            return
        }
        if (e.target.closest("svg")) {
            return
        }
        if (this.table.tabulatorOptions["ajaxConfig"]["method"] === "POST") {
            const selectedViewParams = {
                "selectedView": view_id
            }
            let new_path = window.location.pathname
            if (view_id) {
                new_path += "?" + new URLSearchParams(selectedViewParams).toString()
            }
            history.pushState({}, "", new_path)
        } else {
            const savedParams = JSON.parse(params) || {}
            const allParams = this.table.getAllUrlParams()
            allParams[this.table.viewId] = savedParams
            history.pushState({}, "", window.location.pathname + this.table.paramsObjectToUrlString(allParams))
        }
        this.table.loadFromUrl()
    }
}
