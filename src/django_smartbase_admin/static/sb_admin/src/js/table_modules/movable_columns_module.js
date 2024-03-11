import {SBAdminTableModule} from "./base_module"


export class MovableColumnsModule extends SBAdminTableModule {
    dragFormatter() {
        return `<div class="absolute inset-0 p-8 flex-center" title="${window.sb_admin_translation_strings["reorder"]}"><svg class="w-16 h-16"><use xlink:href="#Hamburger-button"></use></svg></div>`
    }

    getRowPosition(row) {
        const currentPage = row.getTable().getPage() - 1
        const pageSize = row.getTable().getPageSize()
        return currentPage * pageSize + row.getPosition(true)
    }

    getPagePositions(table) {
        const currentPage = table.getPage()
        const pageSize = table.getPageSize()
        const startPosition = (currentPage - 1) * pageSize
        const endPosition = currentPage * pageSize
        return {startPosition: startPosition, endPosition: endPosition}
    }

    isPositionInPage(pagePositions, position) {
        return position >= pagePositions.startPosition && position < pagePositions.endPosition
    }

    maxRowPosition(table) {
        return table.modules.page.remoteRowCountEstimate
    }

    moveRowToPosition(row, position, upOverride = null) {
        if (position <= 0) {
            return
        }
        const table = row.getTable()
        const newRowPosition = position - 1
        if (position > this.maxRowPosition(table)) {
            position = this.maxRowPosition(table)
        }
        let up = true
        if (position > this.getRowPosition(row)) {
            up = false
        }
        if (upOverride !== null) {
            up = upOverride
        }
        const pageSize = table.getPageSize()
        const pagePositions = this.getPagePositions(table)
        const isPositionInPage = this.isPositionInPage(pagePositions, newRowPosition)
        const rowRelativePosition = newRowPosition - pagePositions.startPosition
        if (!isPositionInPage) {
            let newPage = Math.floor(newRowPosition / pageSize) + 1
            table.setPage(newPage)
            this.moveRowAfterNewData = {'rowData': row.getData(), 'newRowPosition': position, 'up': up}
        }
        if (isPositionInPage) {
            table.moveRow(row, table.getRows()[rowRelativePosition], up)
            this.rowMoved(row)
        }
    }

    rownumEdited(cell) {
        const position = cell.getValue()
        this.moveRowToPosition(cell.getRow(), position)
    }

    rownumFormatter(cell) {
        const position = this.getRowPosition(cell.getRow())
        cell.getRow()._getSelf().oldPosition = position
        return position
    }

    arrowUpFirstFormatter() {
        return `<div class="absolute inset-0 p-8 flex-center" title="${window.sb_admin_translation_strings["first"]}"><svg class="w-16 h-16"><use xlink:href="#Double-up"></use></svg></div>`
    }

    arrowUpFormatter() {
        return `<div class="absolute inset-0 p-8 flex-center" title="${window.sb_admin_translation_strings["up"]}"><svg class="w-16 h-16"><use xlink:href="#Up"></use></svg></div>`
    }

    arrowDownFormatter() {
        return `<div class="absolute inset-0 p-8 flex-center" title="${window.sb_admin_translation_strings["down"]}"><svg class="w-16 h-16"><use xlink:href="#Down"></use></svg></div>`
    }

    arrowDownLastFormatter() {
        return `<div class="absolute inset-0 p-8 flex-center" title="${window.sb_admin_translation_strings["last"]}"><svg class="w-16 h-16"><use xlink:href="#Double-down"></use></svg></div>`
    }

    arrowUpMove(cell) {
        this.moveRowToPosition(cell.getRow(), this.getRowPosition(cell.getRow()) - 1)
    }

    arrowUpFirstMove(cell) {
        this.moveRowToPosition(cell.getRow(), 1)
    }

    arrowDownMove(cell) {
        this.moveRowToPosition(cell.getRow(), this.getRowPosition(cell.getRow()) + 1)
    }

    arrowDownLastMove(cell) {
        this.moveRowToPosition(cell.getRow(), this.maxRowPosition(cell.getTable()))
    }

    beforeDefaultColumns() {
        return [
            {
                rowHandle: true,
                formatter: this.dragFormatter,
                headerSort: false,
                width: 40,
                minWidth: 40,
                visible: true,
            },
            {
                cellClick: (e, cell) => {
                    this.arrowUpFirstMove(cell)
                }, formatter: this.arrowUpFirstFormatter, headerSort: false, width: 40, minWidth: 40, visible: true
            },
            {
                cellClick: (e, cell) => {
                    this.arrowUpMove(cell)
                }, formatter: this.arrowUpFormatter, headerSort: false, width: 40, minWidth: 40, visible: true,
            },
            {
                cellClick: (e, cell) => {
                    this.arrowDownMove(cell)
                }, formatter: this.arrowDownFormatter, headerSort: false, width: 40, minWidth: 40, visible: true,
            },
            {
                cellClick: (e, cell) => {
                    this.arrowDownLastMove(cell)
                }, formatter: this.arrowDownLastFormatter, headerSort: false, width: 40, minWidth: 40, visible: true,
            },
            {
                formatter: (cell) => {
                    return this.rownumFormatter(cell)
                }, headerSort: false, visible: true, editor: "input", cellEdited: (cell) => {
                    this.rownumEdited(cell)
                }
            },
        ]
    }

    modifyTabulatorOptions(tabulatorOptions) {
        tabulatorOptions['movableRows'] = true
        return tabulatorOptions
    }

    rowMoved(row) {
        const currentRowId = row.getData()[this.table.tableIdColumnName]
        const currentRowPosition = row._getSelf().oldPosition
        let replacedRowPosition = row.getPosition(true)
        let replacedRowId = null
        const replacedRow = row.getNextRow()
        if (replacedRow) {
            replacedRowId = replacedRow.getData()[this.table.tableIdColumnName]
        }
        const reformatStart = currentRowPosition < replacedRowPosition ? currentRowPosition : replacedRowPosition
        const reformatEnd = currentRowPosition > replacedRowPosition ? currentRowPosition : replacedRowPosition
        this.table.tabulator.getRows().forEach((row) => {
            const position = row.getPosition(true)
            if (position >= reformatStart && position <= reformatEnd) {
                row.reformat()
            }
        })

        const moveRequestData = new FormData()
        moveRequestData.set('currentRowId', currentRowId)
        moveRequestData.set('replacedRowId', replacedRowId)
        fetch(this.table.tableActionMoveUrl, {
            method: 'POST',
            headers: {
                "X-CSRFToken": window.csrf_token,
            },
            body: moveRequestData
        }).then(response => response.json())
            .then(res => {
                console.log(res)
            })
    }

    afterInit() {
        this.table.tabulator.on("rowMoved", (row) => {
            this.rowMoved(row)
        })
        this.table.tabulator.on("dataProcessed", () => {
            if (this.moveRowAfterNewData) {
                this.table.tabulator.addRow(this.moveRowAfterNewData.rowData).then((row) => {
                    this.moveRowToPosition(row, this.moveRowAfterNewData.newRowPosition, this.moveRowAfterNewData.up)
                    const rows = this.table.tabulator.getRows()
                    if (this.moveRowAfterNewData.up === true) {
                        rows[rows.length - 1].delete()
                    } else {
                        rows[0].delete()
                    }
                    this.moveRowAfterNewData = null
                })
            }
        })
    }
}
