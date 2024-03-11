import {createIcon} from "../utils"
import debounce from "lodash/debounce"
import Sortable from "sortablejs"
import {SBAdminTableModule} from "./base_module"

export class ColumnDisplayModule extends SBAdminTableModule {

    constructor(table) {
        super(table)
        this.defaultVisible = true
        this.defaultCollapsed = false
    }

    requiresHeader() {
        return true
    }

    handleColumnVisibility(col, visible, collapsed, initialisation = false) {
        if (visible) {
            col.show()
        } else {
            col.hide()
        }
        if (visible && collapsed) {
            this.table.tabulator.modules.responsiveLayout.hideColumn(col)
        }
        if (visible && !collapsed) {
            this.table.tabulator.modules.responsiveLayout.showColumn(col)
        }
        if (!visible && collapsed) {
            this.table.tabulator.modules.responsiveLayout.showColumn(col)
            col.hide()
        }
        if (!initialisation) {
            if (!this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field]) {
                this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field] = {}
            }
            this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field][this.table.constants.COLUMNS_DATA_VISIBLE_NAME] = visible
            this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field][this.table.constants.COLUMNS_DATA_COLLAPSED_NAME] = collapsed
            this.table.refreshTableDataIfNotUrlLoad()
        }
    }

    createCheckbox(checkboxId, checked, checkboxClasses=['checkbox'],  ) {
        const wrapper = document.createElement('div')
        wrapper.classList.add('relative')

        const label = document.createElement("label")
        const input = document.createElement("input")

        input.id = checkboxId
        input.name = input.id
        input.type = "checkbox"

        input.classList.add(...checkboxClasses)
        input.checked = checked

        label.htmlFor = input.id

        wrapper.appendChild(input)
        wrapper.appendChild(label)

        return [wrapper, input, label]
    }

    refreshColumnWidget() {
        const dragHandle = '<div class="js-drag-handle cursor-pointer ml-auto"><svg class="w-20 h-20 text-dark-400"><use xlink:href="#Drag"></use></svg></div>'
        const cols = this.table.tabulator.getColumns(true)

        const widget = document.querySelector(`#${this.table.columnWidgetId}`)
        widget.innerHTML = ''

        cols.forEach((colProxy) => {
            const col = colProxy._getSelf()
            const checkboxId = this.table.viewId + '_' + col.field
            const wrapper = document.createElement('li')
            const title = col.getDefinition().title
            if (!title) {
                wrapper.style = "display: none"
            }

            const [checkboxVisible, inputVisible] = this.createCheckbox(
                checkboxId + '_visible',
                this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field][this.table.constants.COLUMNS_DATA_VISIBLE_NAME],
                ['checkbox', 'js-select-all-item']
            )

            const [checkboxCollapsed, inputCollapsed, labelCollapsed] = this.createCheckbox(
                checkboxId + '_collapsed',
                this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field][this.table.constants.COLUMNS_DATA_COLLAPSED_NAME],
                ['checkbox', 'checkbox-icon']
            )
            checkboxCollapsed.classList.add('ml-auto')
            labelCollapsed.appendChild(createIcon('Pin', ['w-16', 'h-16']))
            labelCollapsed.appendChild(createIcon('Pin Filled', ['w-16', 'h-16']))


            inputVisible.addEventListener("change", debounce(() => {
                this.handleColumnVisibility(col, inputVisible.checked, inputCollapsed.checked)
            }, 200))

            inputCollapsed.addEventListener("change", debounce(() => {
                this.handleColumnVisibility(col, inputVisible.checked, inputCollapsed.checked)
            }, 200))

            const dragHandleElem = document.createElement('div')
            dragHandleElem.classList.add('ml-8', '-mr-8')
            dragHandleElem.innerHTML = dragHandle

            const itemTitle = document.createElement('div')
            itemTitle.classList.add('line-clamp-1', 'mr-4')
            itemTitle.innerHTML = title

            wrapper.appendChild(checkboxVisible)
            wrapper.appendChild(itemTitle)
            wrapper.appendChild(checkboxCollapsed)
            wrapper.appendChild(dragHandleElem)
            widget.appendChild(wrapper)
        })

        this.sortable = new Sortable(widget, {
            handle: '.js-drag-handle',
            animation: 150,
            ghostClass: 'bg-primary-50',
            onEnd: (evt) => {
                let oldIndex = evt.oldIndex
                let newIndex = evt.newIndex
                let tableColumns = this.table.tabulator.getColumns()
                let column = tableColumns[oldIndex]
                let colNew = tableColumns[newIndex]
                column.move(colNew, oldIndex < newIndex)
                this.table.updateUrlState()
            }
        })
    }

    sortColumns(columns, columnsData) {
        if (!(columnsData && columnsData['order'] && columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME])) {
            return columns
        }
        let sortedColumns = []
        columnsData['order'].forEach((colField) => {
            columns.forEach((col) => {
                if (col.field === colField) {
                    sortedColumns.push(col)
                    col.visible = columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][colField] !== undefined ? columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][colField][this.table.constants.COLUMNS_DATA_VISIBLE_NAME] : this.defaultVisible
                }
            })
        })
        return sortedColumns
    }

    getUrlParams() {
        const params = {}
        if (this.table.tabulator) {
            const columnOrder = []
            const columns = {}
            this.table.tabulator.getColumns().forEach((colProxy) => {
                columnOrder.push(colProxy.getField())
            })
            if (columnOrder.toString() !== this.table.tableInitialColumnsOrder.toString()) {
                params[this.table.constants.COLUMNS_DATA_NAME] = params[this.table.constants.COLUMNS_DATA_NAME] || {}
                params[this.table.constants.COLUMNS_DATA_NAME][this.table.constants.COLUMNS_DATA_ORDER_NAME] = columnOrder
            }

            Object.keys(this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME]).forEach((colKey) => {
                const colData = this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][colKey]
                const initialCol = this.table.tableInitialColumnsByField[colKey] || {}
                const initialVisible = initialCol.visible
                const initialCollapsed = initialCol.collapsed || false
                const currentCollapsed = colData[this.table.constants.COLUMNS_DATA_COLLAPSED_NAME] || false
                const nonInitialVisible = colData[this.table.constants.COLUMNS_DATA_VISIBLE_NAME] !== initialVisible
                const nonInitialCollapsed = currentCollapsed !== initialCollapsed
                if (nonInitialVisible || nonInitialCollapsed) {
                    columns[colKey] = this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][colKey]
                }
            })
            if (Object.keys(columns).length > 0) {
                params[this.table.constants.COLUMNS_DATA_NAME] = params[this.table.constants.COLUMNS_DATA_NAME] || {}
                params[this.table.constants.COLUMNS_DATA_NAME][this.table.constants.COLUMNS_DATA_COLUMNS_NAME] = columns
            }
        }
        return params
    }

    loadFromUrl() {
        const params = this.table.getParamsFromUrl()
        this.columnsData = params[this.table.constants.COLUMNS_DATA_NAME] || {}
        this.columnsData[this.table.constants.COLUMNS_DATA_ORDER_NAME] = this.columnsData[this.table.constants.COLUMNS_DATA_ORDER_NAME] || this.table.tableInitialColumnsOrder
        this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME] = this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME] || {}
        const columnsUrlDataByField = {}
        const initialColumnsByField = JSON.parse(JSON.stringify(this.table.tableInitialColumnsByField))
        Object.keys(this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME]).forEach((colKey) => {
            columnsUrlDataByField[colKey] = this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][colKey]
        })
        Object.keys(initialColumnsByField).forEach((colKey) => {
            this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][colKey] = columnsUrlDataByField[colKey] || initialColumnsByField[colKey]
        })
        if (this.table.tabulator) {
            this.table.tabulator.setColumns(this.sortColumns(this.table.tableColumns, this.columnsData))
        } else {
            this.table.tableColumns = this.sortColumns(this.table.tableColumns, this.columnsData)
        }
    }

    loadFromUrlAfterInit() {
        this.table.tabulator.getColumns().forEach((colProxy) => {
            const col = colProxy._getSelf()
            if (this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field] === undefined) {
                this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field] = {}
                this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field][this.table.constants.COLUMNS_DATA_VISIBLE_NAME] = col.visible !== undefined ? col.visible : this.defaultVisible
                this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field][this.table.constants.COLUMNS_DATA_COLLAPSED_NAME] = col.collapsed !== undefined ? col.collapsed : this.defaultCollapsed
            }
        })
        this.table.tabulator.getColumns().forEach((colProxy) => {
            const col = colProxy._getSelf()
            this.handleColumnVisibility(col, this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field][this.table.constants.COLUMNS_DATA_VISIBLE_NAME], this.columnsData[this.table.constants.COLUMNS_DATA_COLUMNS_NAME][col.field][this.table.constants.COLUMNS_DATA_COLLAPSED_NAME], true)
        })
        this.refreshColumnWidget()
    }
}
