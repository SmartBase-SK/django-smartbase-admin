import { SBAdminTableModule } from "./base_module"
import { get, unset } from "lodash"
import { parseParamsPayload } from "../url_params_codec"

export class ViewsModule extends SBAdminTableModule {
    COMPARE_IGNORE_KEYS = ['filterData.sb_selected_filter_type']
    COMPARE_IGNORE_EMPTY_KEYS = ['filterData.sb_admin_full_search', 'filterData']

    requiresHeader() {
        return true
    }

    getViewsBar() {
        return document.getElementById(`${this.table.viewId}-views`)
    }

    getViewButtons() {
        return document.querySelectorAll(`#${this.table.viewId}-views .js-view-button`)
    }

    comparesFiltersOnly() {
        return this.getViewsBar()?.closest('[data-views-filters-only]') != null
    }

    getSaveButton() {
        return document.getElementById(`${this.table.viewId}-save-view-modal-button`)
    }

    getUrlParamsInput() {
        return document.getElementById(`${this.table.viewId}-${this.table.constants.URL_PARAMS_NAME}`)
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
        this.COMPARE_IGNORE_EMPTY_KEYS.forEach(key_to_remove => {
            const value = get(params, key_to_remove)
            if (value === "" || (value && typeof value === "object" && Object.keys(value).length === 0)) {
                unset(params, key_to_remove)
            }
        })
        this.COMPARE_IGNORE_KEYS.forEach(key_to_remove => {
            unset(params, key_to_remove)
        })
        return params
    }

    // Get normalized JSON string for comparison (sorted keys)
    normalizeForCompare(params) {
        return JSON.stringify(this.sortObjectKeys(this.filterParamsForCompare(params)))
    }

    isEmptyFilterValue(value) {
        if (value === null || value === undefined || value === '' || value === '[]' || value === '{}') {
            return true
        }
        if (Array.isArray(value)) {
            return value.length === 0
        }
        return typeof value === 'object' && Object.keys(value).length === 0
    }

    // Reduce a params payload to the filters that carry a value — see comparesFiltersOnly.
    filterParamsOnlyForCompare(params) {
        const filterDataName = this.table.constants.FILTER_DATA_NAME
        const filterData = params?.[filterDataName] || {}
        const withValue = Object.fromEntries(
            Object.entries(filterData).filter(([, value]) => !this.isEmptyFilterValue(value))
        )
        return Object.keys(withValue).length > 0 ? {[filterDataName]: withValue} : {}
    }

    refreshViewButtons() {
        const urlParams = JSON.parse(this.table.getUrlParamsStringForSave())
        let saveButton = this.getSaveButton()
        const filtersOnly = this.comparesFiltersOnly()
        const forCompare = (params) => filtersOnly ? this.filterParamsOnlyForCompare(params) : params
        const urlParamsNormalized = this.normalizeForCompare(forCompare(urlParams))
        const nothingToSaveNormalized = this.normalizeForCompare(forCompare({}))
        const searchParams = decodeURI(JSON.stringify(this.filterParamsForCompare(urlParams)))
        this.selectedViewParams = this.table.getAllParamsFromUrl()[this.table.viewId]
        const selectedParamsNormalized = this.normalizeForCompare(forCompare(this.selectedViewParams))

        let selectedView = null
        if (saveButton) {
            saveButton.disabled = true
        }

        this.getViewButtons().forEach((item) => {
            if(!item.dataset.params) {
                return
            }
            const itemParamsNormalized = this.normalizeForCompare(forCompare(parseParamsPayload(item.dataset.params)))
            // Fast string comparison with sorted keys
            const sameAsUrlParams = (itemParamsNormalized === urlParamsNormalized)
            const sameAsSelectedParams = (selectedParamsNormalized === itemParamsNormalized)
            item.classList.remove("active")
            item.classList.remove("changed")

            if (!this.selectedViewParams && sameAsUrlParams) {
                item.classList.add("active")
                selectedView = item
                this.selectedViewParams = parseParamsPayload(item.dataset.params)
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
        if (!selectedView && urlParamsNormalized !== nothingToSaveNormalized) {
            if (saveButton) {
                saveButton.disabled = false
            }
        }
        // A bar that cannot save (or one already swapped away) has no hidden input to fill.
        const urlParamsInput = this.getUrlParamsInput()
        if (urlParamsInput) {
            urlParamsInput.value = searchParams
        }
    }

    afterUrlStateUpdate() {
        this.refreshViewButtons()
    }

    loadFromUrlAfterInit() {
        this.refreshViewButtons()
    }

    afterInit() {
        document.body.addEventListener('htmx:afterSwap', (event) => {
            if (event.target?.id === `${this.table.viewId}-views-bar`) {
                this.refreshViewButtons()
            }
        })
    }

    openView(e, params, view_id) {
        if (!params) {
            return
        }
        if (e.target.closest("svg")) {
            return
        }
        const savedParams = parseParamsPayload(params) || {}
        if (!this.table.tableHistoryEnabled) {
            this.table.loadFromParams(savedParams)
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
            const allParams = this.table.getAllUrlParams()
            allParams[this.table.viewId] = savedParams
            history.pushState({}, "", window.location.pathname + this.table.paramsObjectToUrlString(allParams))
        }
        this.table.loadFromUrl()
    }
}
