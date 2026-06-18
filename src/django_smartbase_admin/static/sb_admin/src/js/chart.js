import Chart from "chart.js/auto"
import {ensureFilterForm, filterInputValueChangedUtil, filterInputValueChangeListener} from "./utils"

Chart.defaults.font.family = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"'

class SBAdminChart {

    constructor(options) {
        this.options = options
        this.initChart()
        this.initThemeRefresh()
        if (this.options.parentWidgetId) {
            this.registerParentGroup()
        } else {
            this.refreshData()
            document.addEventListener(window.sb_admin_const.TABLE_RELOAD_DATA_EVENT_NAME, () => {
                this.refreshData()
            })
            this.initFilters()
        }
    }

    getGradient(gradientColorStart, gradientColorStop) {
        return (context) => {
            const chart = context.chart
            const {ctx, chartArea} = chart
            const gradient = ctx.createLinearGradient(0, 0, 0, chartArea.bottom - chartArea.top)
            gradient.addColorStop(0, gradientColorStop)
            gradient.addColorStop(1, gradientColorStart)
            return gradient
        }

    }

    initChart() {
        this.options.formId = this.options.formId || `${this.options.widgetId}-filter-form`
        const ctx = document.getElementById(`${this.options.widgetId}-chart`)
        this.chart = new Chart(ctx, {
            type: this.options.chartType,
            data: {},
            options: this.options.chartOptions || {},
            plugins: this.options.chartPlugins || []
        })
    }

    initThemeRefresh() {
        const refreshChartTheme = () => {
            if (this.chart) {
                this.chart.update('none')
            }
        }
        document.body.addEventListener('color-scheme-change', refreshChartTheme)
        if (!window.matchMedia) {
            return
        }
        const media = window.matchMedia('(prefers-color-scheme: dark)')
        if (media.addEventListener) {
            media.addEventListener('change', refreshChartTheme)
        } else if (media.addListener) {
            media.addListener(refreshChartTheme)
        }
    }

    processDatasets(datasets) {
        datasets.forEach(dataset => {
            if (dataset.backgroundColorGradientStart) {
                dataset.backgroundColor = this.getGradient(dataset.backgroundColorGradientStart, dataset.backgroundColor)
            }
        })
        return datasets
    }

    refreshData() {
        ensureFilterForm(this.options.formId)
        const filterForm = document.getElementById(this.options.formId)
        const filterData = (
            filterForm instanceof HTMLFormElement ? new FormData(filterForm) : new FormData()
        ).entries()
        const filterDataNotEmpty = {}
        for (const [key, value] of filterData) {
            if (value) {
                filterDataNotEmpty[key] = value
            }
        }

        fetch(this.options.ajaxUrl + '?' + new URLSearchParams(filterDataNotEmpty), {
            method: 'GET',
            headers: {
                "X-CSRFToken": window.csrf_token,
            },
        }).then(response => response.json())
            .then(res => {
                this.updateData(res.data)
            })
    }

    updateData(data) {
        this.chart.data.labels = data.main.labels
        this.chart.data.datasets = this.processDatasets(data.main.datasets)
        if (this.chart.data.labels.length >= 1) {
            this.chart.canvas.classList.remove('!hidden')
        } else {
            this.chart.canvas.classList.add('!hidden')
        }
        this.chart.update()
        const subWidgets = data.sub_widget
        if (subWidgets) {
            Object.keys(subWidgets).forEach((widgetId) => {
                const valueEl = document.getElementById(widgetId)
                if (valueEl) {
                    valueEl.innerHTML = subWidgets[widgetId]['formatted_value'] || 0
                }
            })
        }
        const subWidgetsCompare = data.sub_widget_compare
        if (subWidgetsCompare) {
            Object.keys(subWidgetsCompare).forEach((widgetId) => {
                const valueEl = document.getElementById(`${widgetId}_compare`)
                if (valueEl) {
                    const subData = (subWidgets && subWidgets[widgetId] && subWidgets[widgetId]['raw_value']) || 0
                    const subDataCompare = subWidgetsCompare[widgetId]['raw_value'] || 0
                    const percentage = (((subData / subDataCompare) - 1) * 100).toFixed(2)
                    if (percentage !== 'NaN' && percentage !== 'Infinity') {
                        valueEl.innerHTML = percentage + "%"
                    } else {
                        valueEl.innerHTML = ''
                    }
                }
            })
        }
        if (this.options.onData) {
            this.options.onData(data)
        }
        this.chart.canvas.dispatchEvent(new CustomEvent('chartDataLoaded'))
    }

    registerParentGroup() {
        window.SBAdminRegisterDashboardSubWidget(this.options.parentWidgetId, {
            widgetId: this.options.widgetId,
            onData: (data) => {
                this.updateData(data)
            },
        })
    }

    initFilters() {
        filterInputValueChangeListener(`[form="${this.options.formId}"]`, (event) => {
            this.refreshData()
            filterInputValueChangedUtil(event.target)
        })
    }
}

window.SBAdminChartClass = SBAdminChart
document.dispatchEvent(new Event('SBAdminChartClassLoaded'))
