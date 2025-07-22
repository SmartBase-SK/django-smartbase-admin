import {TabulatorFull as Tabulator, Renderer} from 'tabulator-tables'
import {ViewsModule} from "./table_modules/views_module"
import {SelectionModule} from "./table_modules/selection_module"
import {ColumnDisplayModule} from "./table_modules/column_display_module"
import {TableParamsModule} from "./table_modules/table_params_module"
import {DetailViewModule} from "./table_modules/detail_view_module"
import {FilterModule} from "./table_modules/filter_module"
import {AdvancedFilterModule} from "./table_modules/advanced_filter_module"
import {MovableColumnsModule} from "./table_modules/movable_columns_module"
import {DataEditModule} from "./table_modules/data_edit_module"
import {FullTextSearchModule} from "./table_modules/full_text_search_module"
import { HeaderTabsModule } from "./table_modules/header_tabs_module"
import { SBAjaxParamsTabulatorModifier } from "./sb_ajax_params_tabulator_modifier"


class SBAdminTable {

    constructor(options) {
        this.initOptions = options
        // default table params module needs to be last due to sorting and pagination loading
        this.moduleInstances = this.initModules(options.modules)
        this.viewId = options.viewId
        this.filterFormId = options.filterFormId
        this.advancedFilterId = options.advancedFilterId
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
        `Retrieve filter data from "storage" -> currently supported storage is URL or HTML button`
        const urlParamsString = window.location.search
        const urlParams = new URLSearchParams(urlParamsString)
        const viewButton = document.querySelector(`.js-view-button[data-view-id="${urlParams.get("selectedView")}"]`)
        let paramsFromUrl
        if(viewButton) {
            paramsFromUrl = {[this.viewId]: JSON.parse(viewButton.dataset.params)}
        } else {
            paramsFromUrl = JSON.parse(urlParams.get(this.constants.BASE_PARAMS_NAME)) || {}
        }
        return paramsFromUrl
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
            this.tabulator.setData()
        }
    }

    refreshTableDataIfNotUrlLoad() {
        if (!this.loadingFromUrl) {
            this.callModuleAction('beforeRefreshTableDataIfNotUrlLoad')
            // apply fixed height to prevent loosing scroll position
            this.tabulator.element.style.height = `${this.tabulator.element.offsetHeight}px`
            this.tabulator.setData().finally(() => {
                // restore height according to options height
                this.tabulator.element.style.height = this.tabulator.options.height
            })
        }
    }

    isFiltered() {
        const filterParams = this.getUrlParams()[this.constants.FILTER_DATA_NAME]
        if(filterParams === undefined) {
            return false
        }
        return Object.values(filterParams).some(val=>val)
    }

    loadFromUrlAfterInit() {
        window.htmx.process(this.tabulator.rowManager.tableElement)
        this.tabulator.on("dataProcessed", (data) => {
            window.htmx.process(this.tabulator.rowManager.tableElement)
            document.body.dispatchEvent(new CustomEvent('tableDataProcessed', {"detail": {"data": data, "isFiltered": this.isFiltered()}}))
        })
        this.callModuleAction('loadFromUrlAfterInit')
        document.body.dispatchEvent(new CustomEvent('tableDataProcessed', {"detail": {"data": this.tabulator.getData(), "isFiltered": this.isFiltered()}}))
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

    ajaxUrlGenerator() {
        this.updateUrlState()
        if (this.tabulatorOptions['ajaxConfig']['method'] === 'POST') {
            return this.tableAjaxUrl
        }
        return this.tableAjaxUrl + this.getUrlParamsString()
    }

    buildTabulatorTable() {
        this.lastTableParams = {}
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

        this.defaultRowSelectionFormatter = Tabulator.moduleBindings.format.formatters.rowSelection
        const self = this

        class ResponsiveLayoutOnDemandPatch extends Tabulator.moduleBindings.responsiveLayout {
            update() {
            }
        }

        Tabulator.moduleBindings.responsiveLayout = ResponsiveLayoutOnDemandPatch

        const tableHeaderVisible = this.callModuleAction('requiresHeader')
        if (!tableHeaderVisible) {
            document.getElementById(this.viewId + "-tabulator-header").style.display = "none"
        }

        class NoRender extends Renderer {
            render() {}
        }
        if(this.tabulatorOptions['renderVertical'] === "no-render") {
            this.tabulatorOptions['renderVertical'] = NoRender
        }
        if(this.tabulatorOptions['renderHorizontal'] === "no-render") {
            this.tabulatorOptions['renderHorizontal'] =NoRender
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
        Tabulator.registerModule(SBAjaxParamsTabulatorModifier)
        this.tabulator = new Tabulator(this.tableElSelector, tabulatorOptions)
        this.tabulator.SBTable = this
        document.addEventListener(window.sb_admin_const.TABLE_RELOAD_DATA_EVENT_NAME, function () {
            self.refreshTableDataIfNotUrlLoad()
        })
        document.addEventListener(window.sb_admin_const.TABLE_UPDATE_ROW_DATA_EVENT_NAME, function (e) {
            if (e.detail && e.detail.rowData) {
                self.tabulator.updateData(e.detail.rowData)
            }
        })
    }

    executeListAction(action_url, no_params, open_in_new_tab = false) {
        const params = this.getUrlParamsString()
        if (this.tabulatorOptions["ajaxConfig"]["method"] === "POST") {
            const urlParams = new URLSearchParams(params)
            let headers = {
                "Content-Type": "application/json",
                "X-TabulatorRequest": true
            }
            headers = {
                ...headers,
                ...JSON.parse(document.body.getAttribute('hx-headers')),
            }
            let filename = ''
            fetch(action_url, {
                method: "POST",
                headers: headers,
                body: JSON.stringify(JSON.parse(urlParams.get(this.constants.BASE_PARAMS_NAME)) || {})
            })
                .then(function(response) {
                    if (!response.ok) {
                        throw new Error("Network response was not ok " + response.statusText)
                    }
                    if (response.redirected) {
                        window.location.href = response.url
                    }
                    const header = response.headers.get('Content-Disposition')
                    const parts = header.split(';')
                    filename = parts[1].split('=')[1]
                    return response.blob()
                })
                .then(function(blob) {
                    const url = window.URL.createObjectURL(blob)
                    const a = document.createElement("a")
                    a.style.display = "none"
                    a.href = url
                    a.download = filename
                    document.body.appendChild(a)
                    a.click()
                    window.URL.revokeObjectURL(url)
                })
                .catch(function(error) {
                    console.error("There was a problem with the fetch operation:", error)
                })
        } else {
            if (!no_params) {
                action_url += params
            }
            if (open_in_new_tab) {
                window.open(action_url, '_blank')
            } else {
                window.location.href = action_url
            }
        }
    }
}

window.SBAdminTableClass = SBAdminTable
window.SBAdminTableModulesClass = {
    'viewsModule': ViewsModule,
    'selectionModule': SelectionModule,
    'columnDisplayModule': ColumnDisplayModule,
    'filterModule': FilterModule,
    'advancedFilterModule': AdvancedFilterModule,
    'tableParamsModule': TableParamsModule,
    'detailViewModule': DetailViewModule,
    'movableColumnsModule': MovableColumnsModule,
    'dataEditModule': DataEditModule,
    'fullTextSearchModule': FullTextSearchModule,
    'headerTabsModule': HeaderTabsModule,
}
