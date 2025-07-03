import {filterInputValueChangedUtil, filterInputValueChangeListener} from "./utils"

class SBAdminCalendar {
    constructor(options) {
        this.options = options
        this.calendar = null
        this.options['calendarOptions'] = this.options['calendarOptions'] || {}

        if(!Object.hasOwn(this.options.calendarOptions, "events") || !this.options.calendarOptions.events) {
            throw Error('Missing events property!')
        }
        if(typeof this.options.calendarOptions.events === 'string') {
            this.options.calendarOptions.events = {
                url: this.options.calendarOptions.events
            }
        }
        this.options.calendarOptions.events['extraParams'] = this.options.calendarOptions.events['extraParams'] || {}
        this.options.calendarOptions.events.extraParams = () => {
            return {
                ...this.options.calendarOptions.events['extraParams'] || {},
                ...this.getFilterData()
            }
        }
        this.initCalendar()
        this.initFilters()
    }
    
    initCalendar() {
        const calendarEl = document.getElementById(`${this.options.widgetId}-calendar`)

        // eslint-disable-next-line no-undef
        this.calendar = new FullCalendar.Calendar(calendarEl, this.options.calendarOptions || {})
        this.calendar.render()
    }

    getFilterData() {
        const filterForm = document.querySelector(`#${this.options.widgetId}-filter-form`)
        const filterData = new FormData(filterForm).entries()
        const filterDataNotEmpty = {}
        for (const [key, value] of filterData) {
            if (value) {
                filterDataNotEmpty[key] = value
            }
        }
        return filterDataNotEmpty
    }

    initFilters() {
        filterInputValueChangeListener(`[form="${this.options.widgetId}-filter-form"]`, (event) => {
            this.calendar.refetchEvents()
            filterInputValueChangedUtil(event.target)
        })
    }
}

window.SBAdminCalendarClass = SBAdminCalendar