import { SBAdminTableModule } from "./base_module"
import { filterInputValueChangedUtil, filterInputValueChangeListener } from "../utils"
import {customActionsPlugin, HIDE_CALENDAR_CLASS, monthYearViewsPlugin} from "../datepicker_plugins"

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
            ".js-datepicker-dynamic": (rule, ruleEl, widgetEl) => {
                this.dateOperatorUpdate(rule, ruleEl, widgetEl)
            }
        }
        this.afterUpdateRuleOperatorFunctions = {
            ".js-range": this.rangeOperatorUpdate,
            ".js-datepicker-dynamic": this.dateOperatorUpdate.bind(this)
        }
    }

    loadFromUrl() {
        const params = this.table.getParamsFromUrl()
        const emptyRules = {
            "condition": "AND",
            "rules": [{empty: true}]
        }
        let filterData = params[this.table.constants.ADVANCED_FILTER_DATA_NAME]
        if(!filterData?.rules || filterData.rules.length === 0) {
            filterData = emptyRules
        }
        document.querySelectorAll('.js-datepicker-dynamic').forEach(widgetEl => {
            this.destroyDatePicker(widgetEl)
        })
        window.dispatchEvent(new CustomEvent("SBinitOrUpdateQueryBuilder", { detail: { SBTable: this, filterData: filterData } }))
    }

    afterInit() {
        document.addEventListener("click", (event) => {
            const executeButton = event.target.closest("[data-execute]")
            if(executeButton) {
                this.table.refreshTableDataIfNotUrlLoad()
            }
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
        const rules = $(queryBuilder).queryBuilder("getRules", { allow_invalid: true, skip_empty: true })
        return {
            [this.table.constants.ADVANCED_FILTER_DATA_NAME]: rules
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

    destroyDatePicker(widgetEl) {
        if(widgetEl._flatpickr){
            widgetEl._flatpickr.calendarContainer?.remove()
            widgetEl._flatpickr.clear()
            widgetEl._flatpickr.destroy()
        }
    }

    dateOperatorUpdate(rule, ruleEl, widgetEl) {
        let optionsOverride = {
            inline: false,
            mode: "single",
            allowInput: true,
            plugins: [
                monthYearViewsPlugin,
                customActionsPlugin
            ],
        }
        if (["between", "not_between", "in_the_last", "in_the_next"].includes(rule.operator.type)) {
            optionsOverride["mode"] = "range"
        }
        if (["in_the_last", "in_the_next"].includes(rule.operator.type)) {
            // this option does work but there is a bug in certain cases
            // optionsOverride["noCalendar"] = true
            widgetEl.classList.add(HIDE_CALENDAR_CLASS)
        }
        else {
            widgetEl.classList.remove(HIDE_CALENDAR_CLASS)
        }
        this.destroyDatePicker(widgetEl)
        const shortcuts = JSON.parse(widgetEl.dataset.sbadminDatepickerShortcutsDict)
        widgetEl.dataset.sbadminDatepickerShortcuts = JSON.stringify(shortcuts[rule.operator.type] || [])
        window.SBAdmin.datepicker.initFlatPickr(widgetEl, {}, optionsOverride)
    }
}
