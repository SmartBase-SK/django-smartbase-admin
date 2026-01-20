import {SBAdminTableModule} from "./base_module"
import {filterInputValueChangedUtil, filterInputValueChangeListener} from "../utils"

export class FilterModule extends SBAdminTableModule {
    requiresHeader() {
        return true
    }

    afterInit() {
        filterInputValueChangeListener(`[form=${this.table.filterFormId}]`, (event) => {
            this.table.refreshTableDataIfNotUrlLoad()
            this.filterInputValueChanged(event.target)
        })
    }

    loadFromUrl() {
        const params = this.table.getParamsFromUrl()
        const filterData = params[this.table.constants.FILTER_DATA_NAME]
        document.querySelector(`#${this.table.filterFormId}`).reset()
        document.querySelectorAll(`[form=${this.table.filterFormId}]`).forEach((el) => {
            const wrapperEl = el.closest('.filter-wrapper')
            if(wrapperEl) {
                if (!wrapperEl.hasAttribute('data-all-filters-visible')) {
                    this.hideFilter(wrapperEl.getAttribute('data-filter-input-name'))
                }
            } else {
                this.hideFilter(el.getAttribute('name'), false)
            }
        })
        if (filterData) {
            Object.entries(filterData).forEach((item) => {
                let formField = this.getFormField(item[0])
                if (formField) {
                    this.showFilter(item[0], false)
                    formField.value = item[1]
                    formField.dispatchEvent(new CustomEvent('SBTableFilterFormLoad'))
                    this.filterInputValueChanged(formField)
                }
            })
        }
    }

    getFormField(field) {
        return document.querySelector(`#${this.table.viewId}-${field}`)
    }

    filterInputValueChanged(field) {
        const valueElem = filterInputValueChangedUtil(field)
        if (!valueElem) {
            return
        }
        this.changeFilterButtonState(valueElem)
    }

    changeFilterButtonState(valueElem) {
        const dropdownButton = valueElem.closest('button')
        if (valueElem.innerHTML) {
            dropdownButton.classList.remove('empty')
            if (dropdownButton?.dataset?.sbadminCloseOnChange === '1') {
                window.bootstrap5?.Dropdown?.getInstance(dropdownButton)?.hide()
            }
            return
        }
        dropdownButton.classList.add('empty')
    }

    getUrlParams() {
        const params = {}
        const filterForm = document.querySelector(`#${this.table.filterFormId}`)
        const filterData = new FormData(filterForm).entries()
        const filterDataNotEmpty = {}
        for (const [key, value] of filterData) {
            filterDataNotEmpty[key] = value
        }
        if (Object.keys(filterDataNotEmpty).length > 0) {
            params[this.table.constants.FILTER_DATA_NAME] = filterDataNotEmpty
        }
        return params
    }

    focusOnFilterInput(filterElem) {
        setTimeout(() => {
            filterElem.children[0].click()
            filterElem.querySelector('input:not([type="hidden"])')?.focus()
        }, 100)
    }

    showFilter(field, focus = true) {
        const fieldElem = this.getFormField(field)
        const filterElem = document.querySelector(`#${this.table.viewId}-${field}-wrapper`)
        if (!filterElem) {
            return
        }
        if (focus && (!filterElem || !filterElem.classList.contains('hidden'))) {
            // TODO: why it's here
            this.focusOnFilterInput(filterElem)
            return
        }
        fieldElem.disabled = false
        filterElem.classList.remove('hidden')
        if (focus) {
            this.focusOnFilterInput(filterElem)
        }
        this.table.refreshTableDataIfNotUrlLoad()
    }

    hideFilter(field, hideWrapper=true) {
        const fieldElem = this.getFormField(field)
        const filterElem = document.querySelector(`#${this.table.viewId}-${field}-wrapper`)
        if (!fieldElem) {
            return
        }
        fieldElem.value = ''
        if(filterElem && hideWrapper) {
            filterElem.classList.add('hidden')
            fieldElem.disabled = true
        }
        fieldElem.dispatchEvent(new Event('change'))
        fieldElem.dispatchEvent(new CustomEvent('clear'))
        this.table.refreshTableDataIfNotUrlLoad()
    }

    clearFilter(field) {
        const fieldElem = this.getFormField(field)
        fieldElem.value = ''
        fieldElem.dispatchEvent(new Event('change'))
        fieldElem.dispatchEvent(new CustomEvent('clear', {detail: {refresh: true}}))
        this.table.refreshTableDataIfNotUrlLoad()
    }
}
