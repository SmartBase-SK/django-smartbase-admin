import {TabulatorFull as Tabulator} from 'tabulator-tables'
import {ViewsModule} from "./table_modules/views_module"
import {SelectionModule} from "./table_modules/selection_module"
import {ColumnDisplayModule} from "./table_modules/column_display_module"
import {TableParamsModule} from "./table_modules/table_params_module"
import {DetailViewModule} from "./table_modules/detail_view_module"
import {FilterModule} from "./table_modules/filter_module"
import {MovableColumnsModule} from "./table_modules/movable_columns_module"
import {DataEditModule} from "./table_modules/data_edit_module"


class SBAdminTable {

    constructor(options) {
        this.initOptions = options
        // default table params module needs to be last due to sorting and pagination loading
        this.moduleInstances = this.initModules(options.modules)
        this.viewId = options.viewId
        this.filterFormId = options.filterFormId
        this.columnWidgetId = options.columnWidgetId
        this.paginationWidgetId = options.paginationWidgetId
        this.pageSizeWidgetId = options.pageSizeWidgetId
        this.baseViewUrl = options.baseViewUrl
        this.tableElSelector = options.tableElSelector
        this.tableAjaxUrl = options.tableAjaxUrl
        this.tableDataEditUrl = options.tableDataEditUrl
        this.tableActionMoveUrl = options.tableActionMoveUrl
        this.tableDetailUrl = options.tableDetailUrl
        this.defaultColumnData = options.defaultColumnData
        this.tableColumns = this.initDefaultColumns(options.tableColumns)
        this.tableIdColumnName = options.tableIdColumnName
        this.tableInitialSort = options.tableInitialSort
        this.tableInitialPage = options.tableInitialPage || 1
        this.tableInitialPageSize = options.tableInitialPageSize
        this.tableHistoryEnabled = options.tableHistoryEnabled
        this.constants = options.constants
        this.tabulatorOptions = options.tabulatorOptions

        this.tableInitializeSort = this.tableInitialSort
        this.tableInitializePage = this.tableInitialPage
        this.tableInitializePageSize = this.tableInitialPageSize

        this.loadFromUrl()
        this.buildTabulatorTable()
        this.afterInit()
    }

    afterInit() {
        const self = this
        window.addEventListener("popstate", () => {
            self.loadFromUrl()
        })
        this.tabulator.on("tableBuilt", () => {
            self.loadFromUrlAfterInit()
            self.callModuleAction('afterInit')
        })
        document.getElementById('table-selected-rows-bar-select-all')?.addEventListener('change', () => {
            document.getElementById('row-select-all').click()
        })
    }

    getAllParamsFromUrl() {
        const urlParamsString = window.location.search
        const urlParams = new URLSearchParams(urlParamsString)
        this.paramsFromUrl = JSON.parse(urlParams.get(this.constants.BASE_PARAMS_NAME)) || {}
        return this.paramsFromUrl
    }

    getParamsFromUrl() {
        const allParams = this.getAllParamsFromUrl()
        return allParams[this.viewId] || {}
    }

    loadFromUrl() {
        // sets global variable that prevents initial load to alter history, is turned off after initial
        // updateUrlState call
        this.loadingFromUrl = true
        this.callModuleAction('loadFromUrl')
        if (this.tabulator) {
            this.loadFromUrlAfterInit()
            this.tabulator.replaceData()
        }
    }

    refreshTableDataIfNotUrlLoad() {
        if (!this.loadingFromUrl) {
            // apply fixed height to prevent loosing scroll position
            this.tabulator.element.style.height = `${this.tabulator.element.offsetHeight}px`
            this.tabulator.replaceData().finally(() => {
                // restore height according to options height
                this.tabulator.element.style.height = this.tabulator.options.height
            })
        }
    }

    loadFromUrlAfterInit() {
        this.tabulator.on("dataProcessed", () => {
            window.htmx.process(this.tabulator.rowManager.tableElement)
        })
        this.callModuleAction('loadFromUrlAfterInit')
    }

    initModules(modules) {
        let modulesInitialised = {}
        modules.forEach((item) => {
            const moduleClass = window.SBAdminTableModulesClass[item]
            modulesInitialised[item] = new moduleClass(this)
        })
        return modulesInitialised
    }

    initDefaultColumns(columns) {
        columns = [...this.callModuleAction('beforeDefaultColumns'), ...columns]
        this.tableInitialColumnsByField = {}
        this.tableInitialColumnsOrder = []
        const processedColumns = []
        columns.forEach(column => {
            processedColumns.push({...this.defaultColumnData, ...column})
            this.tableInitialColumnsByField[column.field] = JSON.parse(JSON.stringify(column))
            this.tableInitialColumnsOrder.push(column.field)
        })
        return processedColumns
    }

    callModuleAction(action, ...parameters) {
        let result = null
        let resultArray = []
        let arrayResponse = false
        Object.values(this.moduleInstances).forEach(function (module) {
            let actionResult = {}
            try {
                actionResult = module[action](...parameters)
            } catch (e) {
                console.warn(e)
            }
            if (Array.isArray(actionResult)) {
                arrayResponse = true
                resultArray.push(...actionResult)
            } else if (typeof actionResult == "boolean") {
                if (result === null) {
                    result = false
                }
                result = result || actionResult
            } else {
                if (result === null) {
                    result = {}
                }
                result = {...actionResult, ...result}
            }
        })
        if (arrayResponse) {
            return resultArray
        }
        return result
    }

    updateUrlState() {
        // prevent url state update on init (full-refresh or history modification)
        if (!this.loadingFromUrl) {
            if (this.tableHistoryEnabled) {
                history.pushState({}, "", this.baseViewUrl + this.getUrlParamsString())
            }
            this.callModuleAction('afterUrlStateUpdate')
            document.dispatchEvent(new CustomEvent('SBAdminTableNewURL'))
        }
        this.loadingFromUrl = false
    }

    getAllUrlParams() {
        const allParams = this.getAllParamsFromUrl()
        allParams[this.viewId] = this.getUrlParams()
        return allParams
    }

    getUrlParams() {
        const params = this.callModuleAction('getUrlParams')
        return params
    }

    getUrlParamsForSave() {
        const params = this.callModuleAction('getUrlParamsForSave')
        return params
    }

    getUrlParamsStringForSave() {
        let params = this.getUrlParamsForSave()
        return JSON.stringify(params)
    }

    paramsObjectToUrlString(params) {
        return "?" + this.constants.BASE_PARAMS_NAME + "=" + encodeURIComponent(JSON.stringify(params))
    }

    getUrlParamsString() {
        let params = this.getAllUrlParams()
        return this.paramsObjectToUrlString(params)
    }

    ajaxUrlGenerator(url, config, params) {
        this.lastTableParams = params
        this.updateUrlState()
        if (this.tabulatorOptions['ajaxConfig']['method'] === 'POST') {
            return this.tableAjaxUrl
        }
        return this.tableAjaxUrl + this.getUrlParamsString()
    }

    buildTabulatorTable() {
        this.defaultRowSelectionFormatter = Tabulator.moduleBindings.format.formatters.rowSelection
        const self = this

        class ResponsiveLayoutOnDemandPatch extends Tabulator.moduleBindings.responsiveLayout {
            update() {
            }
        }

        Tabulator.moduleBindings.responsiveLayout = ResponsiveLayoutOnDemandPatch
        Tabulator.extendModule("format", "formatters", {
            detail_link: function (cell) {
                const dataId = cell.getData()[self.tableIdColumnName]
                let cellContent = cell.getValue()
                if (!cellContent) {
                    cellContent = '-'
                }
                return "<a href='" + self.tableDetailUrl.replace(self.constants.OBJECT_ID_PLACEHOLDER, dataId) + "'>" + cellContent + "</a>"
            }
        })

        const tableHeaderVisible = this.callModuleAction('requiresHeader')
        if (!tableHeaderVisible) {
            document.getElementById(this.viewId + "-tabulator-header").style.display = "none"
        }

        let tabulatorOptions = {
            columns: this.tableColumns,
            ajaxURL: this.tableAjaxUrl,
            initialSort: this.tableInitializeSort,
            paginationInitialPage: this.tableInitializePage,
            paginationSize: this.tableInitializePageSize,
            ajaxURLGenerator: (url, config, params) => {
                return this.ajaxUrlGenerator(url, config, params)
            },
            ajaxParams: () => {
                if (this.tabulatorOptions['ajaxConfig']['method'] === 'POST') {
                    return this.getAllUrlParams()
                }
                return {}
            },
            dataSendParams: {
                "size": this.constants.TABLE_PARAMS_SIZE_NAME,
                "page": this.constants.TABLE_PARAMS_PAGE_NAME,
                "sort": this.constants.TABLE_PARAMS_SORT_NAME,
            },
            ...this.tabulatorOptions
        }
        if (tabulatorOptions['ajaxConfig']['method'] === 'POST'){
            this.tableHistoryEnabled = false
        }
        tabulatorOptions['ajaxConfig']['headers']['X-CSRFToken'] = window.csrf_token
        tabulatorOptions['ajaxConfig']['headers']['X-TabulatorRequest'] = true
        tabulatorOptions = this.callModuleAction('modifyTabulatorOptions', tabulatorOptions)
        this.tabulator = new Tabulator(this.tableElSelector, tabulatorOptions)
        document.addEventListener("SBAdminReloadTableData", function () {
            self.refreshTableDataIfNotUrlLoad()
        })
    }
}

window.SBAdminTableClass = SBAdminTable
window.SBAdminTableModulesClass = {
    'viewsModule': ViewsModule,
    'selectionModule': SelectionModule,
    'columnDisplayModule': ColumnDisplayModule,
    'filterModule': FilterModule,
    'tableParamsModule': TableParamsModule,
    'detailViewModule': DetailViewModule,
    'movableColumnsModule': MovableColumnsModule,
    'dataEditModule': DataEditModule,
}
