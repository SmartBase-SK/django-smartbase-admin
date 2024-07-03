import Chart from "chart.js/auto"
import {filterInputValueChangedUtil, filterInputValueChangeListener} from "./utils"

Chart.defaults.font.family = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"'

class SBAdminChart {

    constructor(options) {
        this.options = options
        this.initChart()
        this.initFilters()
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
        const ctx = document.getElementById(`${this.options.widgetId}-chart`)
        this.chart = new Chart(ctx, {
            type: this.options.chartType,
            data: {},
            options: {
                scales: {
                    x: {
                        ticks: {
                            font: {
                                weight: 600,
                            }
                        }
                    },
                    y: {
                        ticks: {
                            font: {
                                weight: 600,
                            }
                        }
                    }
                }
            }
        })
        this.refreshData()
        document.addEventListener(window.sb_admin_const.TABLE_RELOAD_DATA_EVENT_NAME, () => {
            this.refreshData()
        })
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
        const filterForm = document.querySelector(`#${this.options.widgetId}-filter-form`)
        const filterData = new FormData(filterForm).entries()
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
                this.chart.data.labels = res.data.main.labels
                this.chart.data.datasets = this.processDatasets(res.data.main.datasets)
                if (this.chart.data.labels.length > 1) {
                    this.chart.canvas.classList.remove('!hidden')
                } else {
                    this.chart.canvas.classList.add('!hidden')
                }
                this.chart.update()
                const subWidgets = res.data.sub_widget
                if (subWidgets) {
                    Object.keys(subWidgets).forEach((widgetId) => {
                        const valueEl = document.getElementById(widgetId)
                        if (valueEl) {
                            valueEl.innerHTML = subWidgets[widgetId]['formatted_value'] || 0
                        }
                    })
                }
                const subWidgetsCompare = res.data.sub_widget_compare
                if (subWidgetsCompare) {
                    Object.keys(subWidgetsCompare).forEach((widgetId) => {
                        const valueEl = document.getElementById(`${widgetId}_compare`)
                        if (valueEl) {
                            const subData = subWidgets[widgetId]['raw_value'] || 0
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
            })
    }

    initFilters() {
        filterInputValueChangeListener(`[form="${this.options.widgetId}-filter-form"]`, (event) => {
            this.refreshData()
            filterInputValueChangedUtil(event.target)
        })
    }
}

window.SBAdminChartClass = SBAdminChart
