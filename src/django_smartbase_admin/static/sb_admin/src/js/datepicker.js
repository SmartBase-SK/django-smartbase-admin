import flatpickr from "flatpickr"
import {createIcon} from "./utils"
import {customActionsPlugin, HIDE_CALENDAR_CLASS, monthYearViewsPlugin} from "./datepicker_plugins"


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
                if(datePickerEl.classList.contains(HIDE_CALENDAR_CLASS)) {
                    instance.monthNav.classList.add('!hidden')
                    instance.innerContainer.classList.add('!hidden')
                }
            },
            onClose: function(selectedDates, dateStr, instance) {
                // fix single day range
                if(instance.config.mode === "range" && selectedDates.length === 1){
                    instance.setDate([selectedDates[0],selectedDates[0]], true)
                }
            },
            ...options,
            ...sbadminDatepickerData.flatpickrOptions,
            ...optionsOverride
        })
    }

    initWidgets(parentEl=null) {
        const datePickerSelector = {
            '.js-datepicker': {
                dateFormat: "d.m.Y",
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
