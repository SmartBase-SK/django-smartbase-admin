import flatpickr from "flatpickr"
import {monthToStr} from "flatpickr/dist/esm/utils/formatting"
import {createIcon} from "./utils"
// eslint-disable-next-line no-unused-vars
const monthYearViewsPlugin = (fp) => {
    const customViewsWrapper = document.createElement('div')
    customViewsWrapper.classList.add('flatpickr-custom-views-wrapper')

    const customMonthsView = document.createElement('div')
    customMonthsView.classList.add('flatpickr-custom-months-view', 'hidden')

    const customYearsView = document.createElement('div')
    customYearsView.classList.add('flatpickr-custom-years-view', 'hidden')

    customViewsWrapper.append(customMonthsView)
    customViewsWrapper.append(customYearsView)

    const yearElHeight = 48
    const yearScrollToElement = 106

    let currentYearEl = null

    const changeActiveView = (view) => {
        switch (view) {
            case 'months':
                customMonthsView.classList.remove('hidden')
                customYearsView.classList.add('hidden')
                break
            case 'years':
                customMonthsView.classList.add('hidden')
                customYearsView.classList.remove('hidden')
                currentYearEl.parentNode.scrollTop = yearElHeight * yearScrollToElement
                break
            default:
                customMonthsView.classList.add('hidden')
                customYearsView.classList.add('hidden')
        }
    }

    const selectMonth = (e) => {
        fp.changeMonth(parseInt(e.target.dataset.month), false)
        buildMonths()
        buildYears()
        changeActiveView()
    }

    const selectYear = (e) => {
        fp.changeYear(parseInt(e.target.dataset.year), false)
        buildMonths()
        buildYears()
        changeActiveView("months")
    }

    const yearInRange = (year, selectedYears) => {
        if (selectedYears[0] && selectedYears[1]) {
            return selectedYears[0] <= year && year <= selectedYears[1]
        }
        return selectedYears[0] === year
    }

    const monthInRange = (monthIndex, selectedMonths, selectedYears) => {
        //range
        if (selectedYears[0] && selectedYears[1]) {
            if (selectedYears[0] === selectedYears[1]) {
                if (selectedYears[0] === fp.currentYear) {
                    return selectedMonths[0] <= monthIndex && monthIndex <= selectedMonths[1]
                }
                return false
            }
            if (selectedYears[0] === fp.currentYear && monthIndex >= selectedMonths[0]) {
                return true
            }
            if (selectedYears[0] < fp.currentYear && fp.currentYear < selectedYears[1]) {
                return true
            }
            if (selectedYears[1] === fp.currentYear && monthIndex <= selectedMonths[1]) {
                return true
            }
            return false
        }

        //single value
        if (selectedYears[0] && !selectedYears[1]) {
            if (selectedYears[0] === fp.currentYear && monthIndex === selectedMonths[0]) {
                return true
            }
        }

        return false
    }

    const buildBackButton = (backToView) => {
        const back = document.createElement('div')
        back.classList.add('flatpickr-back')
        back.textContent = "Back"
        fp._bind(back, 'click', (e) => {
            e.preventDefault()
            e.stopPropagation()
            changeActiveView(backToView)
        })
        return back
    }

    const buildMonths = () => {
        customMonthsView.innerHTML = ''
        const monthsHeader = fp.monthNav.cloneNode(true)
        const yearEl = monthsHeader.querySelector('.flatpickr-current-month')
        yearEl.innerHTML = fp.currentYear
        fp._bind(yearEl, 'click', () => {
            changeActiveView('years')
        })

        const prevYear = monthsHeader.querySelector('.flatpickr-prev-month')
        const nextYear = monthsHeader.querySelector('.flatpickr-next-month')

        prevYear.replaceChildren(createIcon('Left-small'))
        nextYear.replaceChildren(createIcon('Right-small'))

        fp._bind(prevYear, 'click', (e) => {
            e.preventDefault()
            e.stopPropagation()
            fp.changeYear(fp.currentYear - 1)
            buildMonths()
            buildYears()
        })
        fp._bind(nextYear, 'click', (e) => {
            e.preventDefault()
            e.stopPropagation()
            fp.changeYear(fp.currentYear + 1)
            buildMonths()
            buildYears()
        })


        const monthsContent = fp.innerContainer.cloneNode(true)
        monthsContent.querySelector('.flatpickr-weekdays').remove()
        const monthsContainer = monthsContent.querySelector('.dayContainer')
        monthsContainer.innerHTML = ''

        const selectedMonths = fp.selectedDates.map(date => {
            return date.getMonth()
        })
        const selectedYears = fp.selectedDates.map(date => {
            return date.getFullYear()
        })

        for (let i = 0; i < 12; i++) {
            const month = document.createElement('span')
            month.classList.add('flatpickr-day', 'flatpickr-month')
            if (i === fp.now.getMonth() && fp.currentYear === fp.now.getFullYear()) {
                month.classList.add('today')
            }

            if (monthInRange(i, selectedMonths, selectedYears)) {
                month.classList.add('selected')
            }

            month.textContent = monthToStr(i, fp.shorthand, fp.l10n)
            month.dataset.month = i.toString()
            month.addEventListener("click", selectMonth)
            monthsContainer.appendChild(month)
        }

        customMonthsView.append(monthsHeader)
        customMonthsView.append(monthsContent)
        customMonthsView.append(buildBackButton())
    }

    const buildYears = () => {
        customYearsView.innerHTML = ''
        const yearsHeader = fp.monthNav.cloneNode(true)
        const yearEl = yearsHeader.querySelector('.flatpickr-current-month')
        yearEl.innerHTML = fp.currentYear

        yearsHeader.querySelector('.flatpickr-prev-month').remove()
        yearsHeader.querySelector('.flatpickr-next-month').remove()


        const yearsContent = fp.innerContainer.cloneNode(true)
        yearsContent.querySelector('.flatpickr-weekdays').remove()
        yearsContent.querySelector('.flatpickr-days').classList.add('h-full', '-mr-8')

        const yearsContainer = yearsContent.querySelector('.dayContainer')
        yearsContainer.classList.add('overflow-auto', 'custom-scrollbar')
        yearsContainer.innerHTML = ''

        const currentYear = fp.now.getFullYear()
        const selectedYears = fp.selectedDates.map(date => {
            return date.getFullYear()
        })

        for (let i = currentYear - 100; i <= currentYear + 100; i++) {
            const year = document.createElement('span')
            year.classList.add('flatpickr-day', 'flatpickr-year')

            if (i === fp.now.getFullYear()) {
                year.classList.add('today')
                currentYearEl = year
            }

            if (yearInRange(i, selectedYears)) {
                year.classList.add('selected')
            }

            year.textContent = i.toString()
            year.dataset.year = i.toString()
            year.addEventListener("click", selectYear)
            yearsContainer.appendChild(year)
        }

        customYearsView.append(yearsHeader)
        customYearsView.append(yearsContent)
        customYearsView.append(buildBackButton("months"))
    }

    const replaceOriginalMonths = () => {
        const currentMonth = fp.monthNav.querySelector('.flatpickr-current-month')
        currentMonth.innerHTML = ''
        currentMonth.textContent = `${monthToStr(fp.currentMonth, fp.shorthand, fp.l10n)} ${fp.currentYear}`
        return currentMonth
    }

    const build = () => {
        fp.monthNav.parentNode.insertBefore(customViewsWrapper, fp.monthNav)

        fp._bind(replaceOriginalMonths(), "click", (e) => {
            e.preventDefault()
            e.stopPropagation()
            changeActiveView('months')
        })

        buildMonths()
        buildYears()
    }

    return {
        onReady: build,
        onChange: [
            replaceOriginalMonths,
            buildMonths,
            buildYears,
        ],
        onMonthChange: replaceOriginalMonths,
        onYearChange: replaceOriginalMonths
    }
}

// eslint-disable-next-line no-unused-vars
const customActionsPlugin = (fp) => {

    const dateFormat = 'd/m/Y'
    const createRadioInput = (id, name, value, label, checked) => {
        const inputWrapperEl = document.createElement('label')
        inputWrapperEl.classList.add('relative', 'block', 'px-12', 'py-8')
        inputWrapperEl.setAttribute('for', id)
        const labelEl = document.createElement('label')
        labelEl.innerText = label
        labelEl.setAttribute('for', id)
        const inputEl = document.createElement('input')
        inputEl.id = id
        inputEl.name = name
        inputEl.value = value
        inputEl.type = 'radio'
        inputEl.classList.add('radio')
        inputEl.checked = checked
        inputWrapperEl.append(inputEl)
        inputWrapperEl.append(labelEl)
        return inputWrapperEl
    }

    const dateTimeReviver = (key, value) => {
        if (key === 'value') {
            const newValue = []
            value.forEach((val) => {
                newValue.push(new Date(val))
            })
            return newValue
        }
        return value
    }

    const createShortcuts = () => {
        const baseId = fp.element.id
        const baseValue = fp.element.value
        const el = document.createElement('div')
        const shortcuts = JSON.parse(fp.element.dataset.sbadminDatepicker, dateTimeReviver).shortcuts
        el.classList.add('flatpickr-shortcuts')
        el.addEventListener('change', (e) => {
            const value = e.target.value
            fp.setDate(shortcuts[value].value, true, dateFormat)
        })

        shortcuts.forEach((shortcut, idx) => {
            const fromDateFormatted = fp.formatDate(shortcut.value[0], fp.config.dateFormat)
            const toDateFormatted = fp.formatDate(shortcut.value[1], fp.config.dateFormat)
            let shortcutValueStr
            if (fromDateFormatted === toDateFormatted) {
                shortcutValueStr = fromDateFormatted
            } else {
                shortcutValueStr = fromDateFormatted + fp.config.locale.rangeSeparator + toDateFormatted
            }
            el.append(createRadioInput(
                `${baseId}_range${idx}`,
                `${baseId}_shortcut`,
                idx,
                shortcut.label,
                baseValue === shortcutValueStr
            ))
        })
        fp.calendarContainer.prepend(el)
    }


    return {
        onReady: createShortcuts,
    }
}


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

    initWidgets() {
        const datePickerSelector = {
            '.js-datepicker': {
                dateFormat: "d.m.Y",
                allowInput: true,
                plugins: [
                    monthYearViewsPlugin,
                ]
            },
            '.js-datepicker-range': {
                inline: true,
                mode: "range",
                plugins: [
                    monthYearViewsPlugin,
                    customActionsPlugin
                ]
            },
            '.js-timepicker': {
                enableTime: true,
                noCalendar: true,
                dateFormat: "H:i",
                time_24hr: true
            },
            '.js-datetimepicker': {
                enableTime: true,
                dateFormat: "d.m.Y H:i",
                time_24hr: true,
                plugins: [
                    monthYearViewsPlugin,
                ]
            }
        }

        Object.keys(datePickerSelector).forEach(selector => {
            document.querySelectorAll(selector).forEach(datePickerEl => {
                let sbadminDatepickerData = {}
                if(datePickerEl.dataset.sbadminDatepicker) {
                    sbadminDatepickerData = JSON.parse(datePickerEl.dataset.sbadminDatepicker)
                }
                flatpickr(datePickerEl, {
                    onReady: (selectedDates, dateStr, instance) => {
                        this.createClear(instance)
                        instance.nextMonthNav?.replaceChildren(createIcon('Right-small'))
                        instance.prevMonthNav?.replaceChildren(createIcon('Left-small'))
                    },
                    ...datePickerSelector[selector],
                    ...sbadminDatepickerData.flatpickrOptions
                })
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
            document.getElementById(`${datePickerInstance.element.id}_custom`).click()
        })
        clear.classList.add('px-12', 'py-8', 'inline-block', 'text-primary', 'text-14')
        el.append(clear)
        datePickerInstance.calendarContainer.append(el)
    }
}
