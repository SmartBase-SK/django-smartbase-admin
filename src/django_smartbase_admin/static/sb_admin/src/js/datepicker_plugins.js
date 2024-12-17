import {monthToStr} from "flatpickr/dist/esm/utils/formatting"
import {createIcon} from "./utils"

// eslint-disable-next-line no-unused-vars
export const monthYearViewsPlugin = (fp) => {
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

    if(fp.config.noCalendar) {
        return {}
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

export const createRadioInput = (id, name, value, label, checked, index) => {
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
    inputEl.classList.add('radio', 'flatpickr-shortcut')
    inputEl.checked = checked
    inputEl.dataset["index"] = index
    inputWrapperEl.append(inputEl)
    inputWrapperEl.append(labelEl)
    return inputWrapperEl
}

// eslint-disable-next-line no-unused-vars
export const customActionsPlugin = (fp) => {
    const createShortcuts = () => {
        const realInput = document.getElementById(fp.element.dataset.sbadminDatepickerRealInputId)
        const baseId = realInput.id
        const baseValue = realInput.value
        const el = document.createElement('div')
        const shortcuts = JSON.parse(fp.element.dataset.sbadminDatepickerShortcuts)
        el.classList.add('flatpickr-shortcuts')
        el.addEventListener('change', (e) => {
            // on shortcut click/change set new value and label to real input element
            const value = e.target.value
            realInput.value = value
            realInput.dataset['label'] = e.target.nextElementSibling.innerText
            realInput.dispatchEvent(new Event('change'))

            // parse new value and set it to flatpicker
            const shortcutValue = shortcuts[e.target.dataset.index].value
            const from = new Date()
            from.setDate(from.getDate() + shortcutValue[0])

            const to = new Date()
            to.setDate(to.getDate() + shortcutValue[1])

            fp.setDate([from, to], false, fp.config.dateFormat)
        })

        shortcuts.forEach((shortcut, idx) => {
            const checked = JSON.stringify(shortcut.value) === baseValue
            if(checked) {
                realInput.dataset['label'] = shortcut.label
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
        fp.calendarContainer.prepend(el)

        realInput.addEventListener('SBTableFilterFormLoad', () => {
            try {
                const shortcutValue = JSON.parse(realInput.value)
                const from = new Date()
                from.setDate(from.getDate() + shortcutValue[0])

                const to = new Date()
                to.setDate(to.getDate() + shortcutValue[1])
                fp.setDate([from, to], false, fp.config.dateFormat)

                shortcuts.forEach((shortcut, idx) => {
                    if(JSON.stringify(shortcut.value) === realInput.value) {
                        document.getElementById(`${baseId}_range${idx}`).checked = true
                        realInput.dataset['label'] = shortcut.label
                    }
                })
            }
            catch {
                fp.setDate(realInput.value, false, fp.config.dateFormat)
            }
        })
    }


    return {
        onReady: createShortcuts,
        onChange: (selectedDates, dateStr, instance) => {
            const checkedShortcut = instance.element.parentElement.querySelector('input.flatpickr-shortcut:checked')
            if(checkedShortcut){
                checkedShortcut.checked = false
            }
        }
    }
}
