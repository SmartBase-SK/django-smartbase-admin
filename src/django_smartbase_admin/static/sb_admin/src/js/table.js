import {TabulatorFull as Tabulator, Renderer, Module} from 'tabulator-tables'
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
import { DataTreeModule } from "./table_modules/data_tree_module"
import { StickyHeaderAndFooterModule } from "./table_modules/sticky_header_and_footer_module"
import { DashboardParentFilterModule } from "./table_modules/dashboard_parent_filter_module"
import { SBAjaxParamsTabulatorModifier } from "./sb_ajax_params_tabulator_modifier"
import { createIcon } from "./utils"
import { registerFitDataFillAvailableSpaceLayout } from "./tabulator_layouts/fit_data_fill_available_space"
import {decodeParamsFromUrl, encodeParamsForUrl, parseParamsPayload} from "./url_params_codec"


class SBAdminColumnOptionsModule extends Module {
    static moduleName = "sbadminColumnOptions"

    constructor(table) {
        super(table)
        this.registerColumnOption("sbadminKeepDataWidth", false)
        this.registerColumnOption("sbadminSystemColumn", false)
    }
}


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
        this.parentWidgetId = options.parentWidgetId
        this.defaultColumnData = options.defaultColumnData
        this.tableColumns = this.initDefaultColumns(options.tableColumns)
        this.tableIdColumnName = options.tableIdColumnName
        this.tableInitialSort = options.tableInitialSort
        this.tableInitialPage = options.tableInitialPage || 1
        this.tableInitialPageSize = options.tableInitialPageSize
        this.tableHistoryEnabled = options.tableHistoryEnabled
        this.paginationPageInputMinPages = options.paginationPageInputMinPages
        this.enableUrlCompression = options.enableUrlCompression !== false
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
            paramsFromUrl = {[this.viewId]: parseParamsPayload(viewButton.dataset.params)}
        } else {
            paramsFromUrl = decodeParamsFromUrl(urlParams.get(this.constants.BASE_PARAMS_NAME))
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

    initTooltipsInTable() {
        const tableEl = this.tabulator?.rowManager?.tableElement
        if (!tableEl || !window.bootstrap5?.Tooltip) return
        tableEl.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
            window.bootstrap5.Tooltip.getOrCreateInstance(el)
        })
    }

    // Single delegated tooltip for all row actions. Attached once to the stable
    // Tabulator wrapper (which survives row re-renders), so freshly rendered rows
    // are covered without re-init and the underlying tooltip is created lazily on
    // hover/focus. Content comes from data-bs-title set in buildAction*.
    initRowActionTooltips() {
        const el = this.tabulator?.element
        if (!el || el._sbRowActionTooltip || !window.bootstrap5?.Tooltip) return
        el._sbRowActionTooltip = new window.bootstrap5.Tooltip(el, {
            selector: '.row-action-link[data-bs-title], .row-action-dropdown[data-bs-title]',
            trigger: 'hover focus',
            container: 'body',
            boundary: 'viewport',
        })
    }

    loadFromUrlAfterInit() {
        window.htmx.process(this.tabulator.rowManager.tableElement)
        this.initTooltipsInTable()
        this.initRowActionTooltips()
        this.tabulator.on("dataProcessed", (data) => {
            window.htmx.process(this.tabulator.rowManager.tableElement)
            this.initTooltipsInTable()
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
        return "?" + this.constants.BASE_PARAMS_NAME + "=" + encodeURIComponent(encodeParamsForUrl(params, this.enableUrlCompression))
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

    _handleAjaxNotifications(response) {
        const html = response?.[this.constants.AJAX_NOTIFICATIONS_KEY]
        if (!html) {
            return
        }
        const slot = document.getElementById("notification-messages")
        if (!slot) {
            return
        }
        slot.innerHTML = html
        window.htmx?.process(slot)
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
            },
            sbadminRowActionsFormatter: function (cell) {
                const actions = cell.getRow().getData()._row_actions || []
                const wrapper = document.createElement('div')
                wrapper.classList.add('row-actions-cell-inner', 'row-prevent-click')

                const getRowActionDropdownPortal = function () {
                    let portal = document.querySelector(
                        `.row-action-dropdown-portal[data-row-action-dropdown-portal="${self.viewId}"]`
                    )
                    if (!portal) {
                        portal = document.createElement('div')
                        portal.classList.add('row-action-dropdown-portal')
                        portal.dataset.rowActionDropdownPortal = self.viewId
                        document.body.append(portal)
                    }
                    return portal
                }

                const safeIdValue = function (value) {
                    return String(value).replace(/[^a-zA-Z0-9_-]/g, '_')
                }

                const actionHasCssClass = function (action, cssClass) {
                    return (action.css_class || '').split(' ').includes(cssClass)
                }

                // Icon-only actions show no visible label, so they get a delegated
                // tooltip (see initRowActionTooltips). Labelled actions don't need one.
                const wantsTooltip = function (action) {
                    return Boolean(action.title) && actionHasCssClass(action, 'btn-only-icon')
                }

                const appendActionTitle = function (element, action) {
                    if (!action.title || actionHasCssClass(action, 'btn-only-icon')) {
                        return
                    }
                    const label = document.createElement('span')
                    label.textContent = action.title
                    label.classList.add('ml-4')
                    element.append(label)
                }

                const configureActionElement = function (element, action) {
                    element.setAttribute('aria-label', action.title || '')
                    if (wantsTooltip(action)) {
                        element.setAttribute('data-bs-title', action.title)
                    }
                    if (action.open_in_modal) {
                        element.setAttribute('data-bs-toggle', 'modal')
                        element.setAttribute('data-bs-target', '#sb-admin-modal')
                        element.setAttribute('hx-get', action.url)
                        element.setAttribute('hx-target', '#sb-admin-modal')
                    } else if (action.is_method_action) {
                        element.setAttribute('hx-post', action.url)
                        element.setAttribute('hx-swap', 'none')
                        element.setAttribute('hx-indicator', '#page-loading')
                    } else {
                        element.href = action.url
                        if (action.is_download) {
                            // The endpoint may take a moment to generate the file.
                            // Fetch it as a blob so the global page-loading overlay
                            // can cover the whole request and hide once it's ready.
                            // href stays set so modified clicks still work as a link.
                            element.addEventListener('click', (event) => {
                                if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) {
                                    return
                                }
                                event.preventDefault()
                                self.downloadWithLoading(action.url)
                            })
                        } else if (action.open_in_new_tab) {
                            element.target = '_blank'
                            element.rel = 'noopener'
                        }
                    }
                }

                const buildActionLink = function (action, dropdownItem = false) {
                    const link = document.createElement('a')
                    if (dropdownItem) {
                        link.classList.add('dropdown-menu-link', 'row-action-dropdown-link', 'btn')
                    } else {
                        link.classList.add('row-action-link')
                        if (action.css_class) {
                            link.classList.add(...action.css_class.split(' ').filter(Boolean))
                        }
                    }
                    configureActionElement(link, action)
                    if (action.icon) {
                        link.append(createIcon(action.icon, ['w-16', 'h-16']))
                    }
                    if (dropdownItem) {
                        link.append(action.title || '')
                    } else {
                        appendActionTitle(link, action)
                    }
                    return link
                }

                const buildActionDropdown = function (action, index) {
                    const rowId = cell.getRow().getData()[self.tableIdColumnName]
                    const buttonId = `${self.viewId}-row-action-dropdown-${safeIdValue(rowId)}-${index}`
                    const menuId = `${buttonId}-menu`

                    const dropdown = document.createElement('div')
                    dropdown.classList.add('relative', 'row-action-dropdown')

                    const button = document.createElement('button')
                    button.id = buttonId
                    button.type = 'button'
                    button.classList.add('row-action-link')
                    if (action.css_class) {
                        button.classList.add(...action.css_class.split(' ').filter(Boolean))
                    }
                    button.setAttribute('aria-label', action.title || '')
                    // The button is a Bootstrap Dropdown; a Tooltip can't share the same
                    // element, so the tooltip lives on the .row-action-dropdown wrapper.
                    if (wantsTooltip(action)) {
                        dropdown.setAttribute('data-bs-title', action.title)
                    }
                    button.setAttribute('data-bs-toggle', 'dropdown')
                    button.setAttribute('data-sbadmin-managed-dropdown', 'row-actions')
                    button.setAttribute('aria-expanded', 'false')
                    button.setAttribute('aria-controls', menuId)
                    button.append(createIcon(action.icon || 'More', ['w-16', 'h-16', 'no-rotate']))
                    appendActionTitle(button, action)

                    const menu = document.createElement('div')
                    menu.id = menuId
                    menu.classList.add('dropdown-menu', 'dropdown-menu-end', 'row-action-dropdown-menu', 'max-h-432')

                    const list = document.createElement('ul')
                    action.sub_actions.forEach((subAction) => {
                        const item = document.createElement('li')
                        item.append(buildActionLink(subAction, true))
                        list.append(item)
                    })
                    menu.append(list)
                    dropdown.append(button)
                    dropdown.append(menu)

                    if (window.bootstrap5?.Dropdown) {
                        new window.bootstrap5.Dropdown(button, {
                            autoClose: true,
                            offset: [0, 8],
                            boundary: 'viewport',
                            popperConfig(defaultBsPopperConfig) {
                                return {
                                    ...defaultBsPopperConfig,
                                    strategy: 'fixed',
                                    placement: 'bottom-end'
                                }
                            }
                        })
                        menu.remove()

                        button.addEventListener('show.bs.dropdown', () => {
                            const portal = getRowActionDropdownPortal()
                            portal.replaceChildren(menu)
                            window.htmx?.process(menu)
                        })

                        button.addEventListener('hidden.bs.dropdown', () => {
                            if (menu.parentElement?.classList.contains('row-action-dropdown-portal')) {
                                menu.remove()
                            }
                        })
                    }

                    return dropdown
                }

                actions.forEach((action, index) => {
                    if (action.sub_actions && action.sub_actions.length) {
                        wrapper.append(buildActionDropdown(action, index))
                        return
                    }
                    const link = buildActionLink(action)
                    wrapper.append(link)
                })
                return wrapper
            }
        })
        registerFitDataFillAvailableSpaceLayout(Tabulator, this.tabulatorOptions)

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
            ajaxResponse: (url, params, response) => {
                self._handleAjaxNotifications(response)
                return response
            },
            dataSendParams: {
                "size": this.constants.TABLE_PARAMS_SIZE_NAME,
                "page": this.constants.TABLE_PARAMS_PAGE_NAME,
                "sort": this.constants.TABLE_PARAMS_SORT_NAME,
            },
            rowFormatter: (row) => {
                const el = row.getElement()
                const prev = el.dataset.sbRowClass
                if (prev) {
                    el.classList.remove(...prev.split(/\s+/).filter(Boolean))
                    delete el.dataset.sbRowClass
                }
                const cls = (row.getData() || {})._row_class
                if (cls) {
                    const tokens = cls.split(/\s+/).filter(Boolean)
                    if (tokens.length) {
                        el.classList.add(...tokens)
                        el.dataset.sbRowClass = tokens.join(' ')
                    }
                }
            },
            ...this.tabulatorOptions
        }
        if (tabulatorOptions['ajaxConfig']['method'] === 'POST'){
            this.tableHistoryEnabled = false
        }
        tabulatorOptions['ajaxConfig']['headers']['X-CSRFToken'] = window.csrf_token
        tabulatorOptions['ajaxConfig']['headers']['X-TabulatorRequest'] = true
        tabulatorOptions = this.callModuleAction('modifyTabulatorOptions', tabulatorOptions)
        Tabulator.registerModule(SBAdminColumnOptionsModule)
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

    downloadWithLoading(url) {
        document.documentElement.classList.add('htmx-request')
        let filename = ''
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function(response) {
                if (!response.ok) {
                    throw new Error("Network response was not ok " + response.statusText)
                }
                const header = response.headers.get('Content-Disposition')
                if (header) {
                    const match = header.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i)
                    if (match) {
                        filename = decodeURIComponent(match[1])
                    }
                }
                return response.blob()
            })
            .then(function(blob) {
                const objectUrl = window.URL.createObjectURL(blob)
                const a = document.createElement("a")
                a.style.display = "none"
                a.href = objectUrl
                a.download = filename
                document.body.appendChild(a)
                a.click()
                a.remove()
                window.URL.revokeObjectURL(objectUrl)
            })
            .catch(function(error) {
                console.error("There was a problem with the download:", error)
                // Fall back to a plain navigation so the user still gets the file.
                window.location.href = url
            })
            .finally(function() {
                document.documentElement.classList.remove('htmx-request')
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
            document.documentElement.classList.add('htmx-request')
            fetch(action_url, {
                method: "POST",
                headers: headers,
                body: JSON.stringify(decodeParamsFromUrl(urlParams.get(this.constants.BASE_PARAMS_NAME)))
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
                .finally(function() {
                    document.documentElement.classList.remove('htmx-request')
                })
        } else {
            if (!no_params) {
                action_url += params
            }
            if (open_in_new_tab) {
                window.open(action_url, '_blank', 'noopener')
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
    'dataTreeModule': DataTreeModule,
    'stickyHeaderAndFooterModule': StickyHeaderAndFooterModule,
    'dashboardParentFilterModule': DashboardParentFilterModule,
}
