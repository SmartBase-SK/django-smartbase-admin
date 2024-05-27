import { SBAdminTableModule } from "./base_module"
import { filterInputValueChangedUtil, filterInputValueChangeListener } from "../utils"

export class AdvancedFilterModule extends SBAdminTableModule {
    constructor(table) {
        super(table)
        this.componentInitMap = {
            ".js-autocomplete": (rule, ruleEl, widgetEl) => {
                window.SBAdmin.autocomplete.initAutocomplete(widgetEl)
            },
            ".js-simple-multiselect": (rule, ruleEl, widgetEl) => {
                window.SBAdmin.multiselect.initMultiselect(widgetEl)
                widgetEl.dispatchEvent(new CustomEvent("SBTableFilterFormLoad"))
            },
            ".js-range": (rule, ruleEl, widgetEl) => {
                window.SBAdmin.range.initRange(widgetEl)
                widgetEl.dispatchEvent(new CustomEvent("SBTableFilterFormLoad"))
            },
            ".js-datepicker-not-inline": (rule, ruleEl, widgetEl) => {
                this.dateOperatorUpdate(rule, ruleEl, widgetEl)
            },
        }
        this.afterUpdateRuleOperatorFunctions = {
            ".js-range": this.rangeOperatorUpdate,
            ".js-datepicker-not-inline": this.dateOperatorUpdate,
        }
    }

    loadFromUrl() {
        window.dispatchEvent(new CustomEvent('SBinitQueryBuilder', {detail: {SBTable: this}}))
    }

    afterInit() {
        document.querySelector("[data-execute]").addEventListener("click", () => {
            this.table.refreshTableDataIfNotUrlLoad()
        })
    }

    initFilters(event, rule) {
        const ruleEl = rule.$el[0]
        Object.keys(this.componentInitMap).forEach(selector => {
            const widgetEl = ruleEl.querySelector(selector)
            if (!widgetEl) {
                return
            }
            this.componentInitMap[selector](rule, ruleEl, widgetEl)
        })


        ruleEl.querySelectorAll(`[form=${this.table.advancedFilterId}]`).forEach(el => {
            filterInputValueChangedUtil(el)
        })
        filterInputValueChangeListener(`[form=${this.table.advancedFilterId}]`, (event) => {
            filterInputValueChangedUtil(event.target)
        })
    }

    afterUpdateRuleOperator(event, rule) {
        const ruleEl = rule.$el[0]
        Object.keys(this.afterUpdateRuleOperatorFunctions).forEach(selector => {
            const widgetEl = ruleEl.querySelector(selector)
            if (!widgetEl) {
                return
            }
            this.afterUpdateRuleOperatorFunctions[selector](rule, ruleEl, widgetEl)
        })
    }

    getUrlParams() {
        const queryBuilder = document.querySelector(`#${this.table.advancedFilterId}`)
        const rules = $(queryBuilder).queryBuilder("getRules", {allow_invalid: true})
        return {
            "advancedFilterData": rules
        }
    }

    rangeOperatorUpdate(rule, ruleEl, widgetEl) {
        const fromEl = ruleEl.querySelector(`[name=${widgetEl.id}_to]`)
        if (["between", "not_between"].includes(rule.operator.type)) {
            fromEl.classList.remove("hidden")
        } else if (!fromEl.classList.contains("hidden")) {
            fromEl.classList.add("hidden")
        }
    }

    dateOperatorUpdate(rule, ruleEl, widgetEl) {
        let newMode = "single"
        if (["between", "not_between"].includes(rule.operator.type)) {
            newMode = "range"
        }
        if (!widgetEl._flatpickr) {
            // not yet initialized, init nad set right mode
            const sbadminDatepickerData = JSON.parse(widgetEl.dataset.sbadminDatepicker)
            sbadminDatepickerData.flatpickrOptions.mode = newMode
            widgetEl.dataset.sbadminDatepicker = JSON.stringify(sbadminDatepickerData)
            window.SBAdmin.datepicker.initWidgets(ruleEl)
        } else {
            // update mode
            const flatPickr = widgetEl._flatpickr
            const currentMode = flatPickr.config.mode

            if (newMode !== currentMode) {
                flatPickr.set("mode", newMode)
                flatPickr.clear()
            }
        }
    }
}
