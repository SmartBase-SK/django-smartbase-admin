import flatpickr from "flatpickr"
import {createIcon} from "./utils"
import {
    createRadioInput,
    customActionsPlugin,
    monthYearViewsPlugin
} from "./datepicker_plugins"


export default class Datepicker {
    constructor() {
        let documentLocale = document.documentElement.lang || 'default'
        if (documentLocale === 'en') {
            documentLocale = 'default'
        }
        flatpickr.localize(this.getLocale(documentLocale))
        this.initWidgets()

        document.addEventListener('formset:added', () => {
            this.initWidgets()
        })
    }

    getLocale(locale) {
        // eslint-disable-next-line no-undef
        const l = require(`flatpickr/dist/l10n/${locale}.js`)
        return l.default[locale]
    }

    initFlatPickr(datePickerEl, options={}, optionsOverride={}) {
        let sbadminDatepickerData = {}
        if(datePickerEl.dataset.sbadminDatepicker) {
            sbadminDatepickerData = JSON.parse(datePickerEl.dataset.sbadminDatepicker)
        }
        flatpickr(datePickerEl, {
            onReady: (selectedDates, dateStr, instance) => {
                const isInTable = datePickerEl.closest('[data-filter-input-name]')
                if(!isInTable) {
                    this.createClear(instance)
                }
                instance.nextMonthNav?.replaceChildren(createIcon('Right-small'))
                instance.prevMonthNav?.replaceChildren(createIcon('Left-small'))
                datePickerEl.addEventListener('clear', () => {
                    instance.clear()
                })
            },
            onClose: function(selectedDates, dateStr, instance) {
                // fix single day range
                if(instance.config.mode === "range" && selectedDates.length === 1){
                    instance.setDate([selectedDates[0],selectedDates[0]], true)
                }
            },
            onChange: function(selectedDates, dateStr) {
                document.getElementById(datePickerEl.dataset.sbadminDatepickerRealInputId).value = dateStr
            },
            ...options,
            ...sbadminDatepickerData.flatpickrOptions,
            ...optionsOverride
        })
    }

    initShortcutsDropdown(datePickerEl) {
        const realInput = document.getElementById(datePickerEl.dataset.sbadminDatepickerRealInputId)
        const baseId = realInput.id
        const baseValue = realInput.value
        const el = document.createElement('div')
        const shortcuts = JSON.parse(datePickerEl.dataset.sbadminDatepickerShortcuts)
        el.classList.add('flatpickr-shortcuts', 'dropdown-menu')
        el.addEventListener('change', (e) => {
            realInput.value = e.target.value
            datePickerEl.value = e.target.nextElementSibling.innerText
        })

        shortcuts.forEach((shortcut, idx) => {
            const checked = JSON.stringify(shortcut.value) === baseValue
            if(checked) {
                datePickerEl.value = shortcut.label
            }
            el.append(createRadioInput(
                `${baseId}_range${idx}`,
                `${baseId}_shortcut`,
                JSON.stringify(shortcut.value),
                shortcut.label,
                checked
            ))
        })
        datePickerEl.parentElement.append(el)
        datePickerEl.readOnly = true
        datePickerEl.dataset['bsToggle'] = "dropdown"
        new window.bootstrap5.Dropdown(datePickerEl)
    }

    initWidgets(parentEl=null) {
        const datePickerSelector = {
            '.js-datepicker': {
                allowInput: true,
                plugins: [
                    monthYearViewsPlugin,
                ],
            },
            '.js-datepicker-range': {
                inline: true,
                mode: "range",
                allowInput: true,
                plugins: [
                    monthYearViewsPlugin,
                    customActionsPlugin
                ],
            },
            '.js-timepicker': {
                enableTime: true,
                noCalendar: true,
                dateFormat: "H:i",
                allowInput: true,
                time_24hr: true,
            },
            '.js-datetimepicker': {
                enableTime: true,
                dateFormat: "d.m.Y H:i",
                allowInput: true,
                time_24hr: true,
                plugins: [
                    monthYearViewsPlugin,
                ],
            }
        }
        if(!parentEl) {
            parentEl = document
        }

        Object.keys(datePickerSelector).forEach(selector => {
            parentEl.querySelectorAll(selector).forEach(datePickerEl => {
                this.initFlatPickr(datePickerEl, datePickerSelector[selector])
            })
        })
    }


    createClear(datePickerInstance) {
        const el = document.createElement('div')
        el.classList.add('flatpickr-footer')
        const clear = document.createElement('a')
        clear.text = 'Clear'
        clear.addEventListener('click', (e) => {
            e.preventDefault()
            datePickerInstance.clear()
        })
        clear.classList.add('px-12', 'py-8', 'inline-block', 'text-primary', 'text-14')
        el.append(clear)
        datePickerInstance.calendarContainer.append(el)
    }
}
