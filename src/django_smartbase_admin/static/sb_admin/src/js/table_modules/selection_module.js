import {SBAdminTableModule} from "./base_module"


export class SelectionModule extends SBAdminTableModule {

    constructor(table) {
        super(table)
        this.tableSelectedRows = new Set()
        this.tableDeselectedRows = new Set()
    }

    setSelectedRows(selectedRows, deselectedRows) {
        if (this.tableSelectionInitialisation) {
            return
        }
        let tableSelectedRowsInfo = document.querySelector('#' + this.table.constants.SELECTED_ROWS_KWARG_NAME + '_info')
        const tableSelectedRowsBar = document.querySelector('#' + this.table.constants.SELECTED_ROWS_KWARG_NAME + '_bar')
        this.tableSelectedRows = selectedRows
        this.tableDeselectedRows = deselectedRows
        if (selectedRows === this.table.constants.SELECT_ALL_KEYWORD) {
            tableSelectedRowsInfo.innerHTML = this.table.tabulator.modules.page.remoteRowCountEstimate - deselectedRows.size
            return
        }
        tableSelectedRowsInfo.innerHTML = `${selectedRows.size} selected`
        if (selectedRows.size > 0) {
            tableSelectedRowsBar.classList.add('show')
            document.getElementById('table-selected-rows-bar-select-all').checked = true
        } else {
            document.getElementById('table-selected-rows-bar-select-all').checked = false
            tableSelectedRowsBar.classList.remove('show')
        }
    }

    selectAllData() {
        this.table.tabulator.selectRow('all')
        this.setSelectedRows(this.table.constants.SELECT_ALL_KEYWORD, new Set())
    }

    selectNoData() {
        this.table.tabulator.deselectRow()
        this.setSelectedRows(new Set(), new Set())
    }

    rowSelectionFormatter(tabulatorFormatterHandle, cell, formatterParams, onRendered) {
        let originalHandler = this.table.defaultRowSelectionFormatter.bind(tabulatorFormatterHandle)
        let checkbox = originalHandler(cell, formatterParams, onRendered)
        let selectedCheckbox = false

        checkbox.setAttribute("aria-label", "Select Row")
        checkbox.classList.add('checkbox')

        const label = document.createElement("label")
        const wrapper = document.createElement("label")
        wrapper.classList.add('row-select-wrapper')

        if (typeof cell.getRow == 'function') {
            let row = cell.getRow()
            let allRowsSelectedAndThisRowNotDeselected = this.tableSelectedRows === this.table.constants.SELECT_ALL_KEYWORD && !this.tableDeselectedRows.has(row.getData()[this.table.tableIdColumnName])
            let thisRowSelected = this.tableSelectedRows !== this.table.constants.SELECT_ALL_KEYWORD && this.tableSelectedRows.has(row.getData()[this.table.tableIdColumnName])
            selectedCheckbox = allRowsSelectedAndThisRowNotDeselected || thisRowSelected
            if (selectedCheckbox) {
                this.tableSelectionInitialisation = true
                row.toggleSelect()
                this.tableSelectionInitialisation = false
            }

            const rowData = row.getData()
            checkbox.setAttribute("id", `row-select-${rowData[this.table.tableIdColumnName]}`)
            checkbox.setAttribute("name", `row-select-${this.table.viewId}`)
            label.setAttribute("for", `row-select-${rowData[this.table.tableIdColumnName]}`)
            wrapper.setAttribute("for", `row-select-${rowData[this.table.tableIdColumnName]}`)
        } else {
            checkbox.setAttribute("id", `row-select-all`)
            label.setAttribute("for", `row-select-all`)
            wrapper.setAttribute("for", `row-select-all`)
            // fix for checkbox outline
            cell.getElement().style = "overflow: visible;"
        }

        wrapper.append(checkbox)
        wrapper.append(label)

        return wrapper
    }

    beforeDefaultColumns() {
        const self = this
        return [
            {
                field: '__selection',
                formatter: function (cell, formatterParams, onRendered) {
                    return self.rowSelectionFormatter(this, cell, formatterParams, onRendered)
                },
                titleFormatter: function (cell, formatterParams, onRendered) {
                    return self.rowSelectionFormatter(this, cell, formatterParams, onRendered)
                },
                visible: true,
                headerSort: false,
                width: '52'
            }
        ]
    }

    getSelectionHandler(selectionType) {
        return (row) => {
            let selectedRows = this.tableSelectedRows
            let deselectedRows = this.tableDeselectedRows
            if (selectionType === "rowDeselected") {
                if (selectedRows === this.table.constants.SELECT_ALL_KEYWORD) {
                    deselectedRows.add(row.getData()[this.table.tableIdColumnName])
                } else {
                    selectedRows.delete(row.getData()[this.table.tableIdColumnName])
                }
            }
            if (selectionType === "rowSelected") {
                if (selectedRows === this.table.constants.SELECT_ALL_KEYWORD) {
                    deselectedRows.delete(row.getData()[this.table.tableIdColumnName])
                } else {
                    selectedRows.add(row.getData()[this.table.tableIdColumnName])
                }
            }
            this.setSelectedRows(selectedRows, deselectedRows)
        }
    }

    getUrlParams() {
        const params = {}
        const selectionData = {}
        const selectedArray = this.table.constants.SELECT_ALL_KEYWORD === this.tableSelectedRows ? this.tableSelectedRows : Array.from(this.tableSelectedRows)
        const deselectedArray = Array.from(this.tableDeselectedRows)
        if (selectedArray.length > 0) {
            selectionData[this.table.constants.SELECTED_ROWS_KWARG_NAME] = selectedArray
        }
        if (deselectedArray.length > 0) {
            selectionData[this.table.constants.DESELECTED_ROWS_KWARG_NAME] = deselectedArray
        }
        if (selectedArray.length > 0 || deselectedArray.length > 0) {
            params[this.table.constants.SELECTION_DATA_NAME] = selectionData
        }
        return params
    }

    getUrlParamsForSave() {
        return {}
    }

    afterInit() {
        this.table.tabulator.on("rowSelected", this.getSelectionHandler("rowSelected"))
        this.table.tabulator.on("rowDeselected", this.getSelectionHandler("rowDeselected"))
    }

    loadFromUrlAfterInit() {
        this.selectNoData()
    }

    beforeRefreshTableDataIfNotUrlLoad() {
        this.selectNoData()
    }
}
