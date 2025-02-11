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
        documentLocale = documentLocale.split('-')[0]
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
                instance.nextMonthNav?.replaceChildren(createIcon('Right-small'))
                instance.prevMonthNav?.replaceChildren(createIcon('Left-small'))

                const isInTable = datePickerEl.closest('[data-filter-input-name]')

                // real input element should be present only in filters
                const realInput = document.getElementById(datePickerEl.dataset.sbadminDatepickerRealInputId)
                const mainInput = realInput || datePickerEl
                mainInput.addEventListener('clear', () => {
                    instance.clear()
                })


                if(!isInTable){
                    this.createClear(instance)
                }

                if(isInTable && realInput) {
                    // set initial value from real input to flatpickr
                    realInput.addEventListener('SBTableFilterFormLoad', () => {
                        if(!datePickerEl.value) {
                            instance.setDate(realInput.value, false, instance.config.dateFormat)
                        }
                    })
                    return
                }
                if(realInput) {
                    // advanced filters
                    instance.setDate(realInput.value, false, instance.config.dateFormat)
                }
            },
            onClose: function(selectedDates, dateStr, instance) {
                // fix single day range
                if(instance.config.mode === "range" && selectedDates.length === 1){
                    instance.setDate([selectedDates[0],selectedDates[0]], true)
                }
            },
            onChange: function(selectedDates, dateStr) {
                const realInput = document.getElementById(datePickerEl.dataset.sbadminDatepickerRealInputId)
                if(realInput) {
                    realInput.value = dateStr
                    realInput.removeAttribute('data-label')
                    realInput.dispatchEvent(new Event('change'))
                }
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
                checked,
                idx
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
