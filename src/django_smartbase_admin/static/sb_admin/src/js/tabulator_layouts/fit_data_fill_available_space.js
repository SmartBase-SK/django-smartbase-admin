// Custom fitData + fitColumns hybrid:
// - if natural fitData width is smaller than table width, grow visible columns to fill space
// - if natural fitData width overflows, keep natural widths so scrollbar appears
const KEEP_DATA_WIDTH_OPTION = "sbadminKeepDataWidth"
const STRETCHED_WIDTH_MODULE_KEY = "sbadminFitDataStretchWidth"

export function registerFitDataFillAvailableSpaceLayout(Tabulator, tabulatorOptions) {
    if(tabulatorOptions.layout !== "fitDataFillAvailableSpace") {
        return
    }

    Tabulator.extendModule("layout", "modes", {
        fitDataFillAvailableSpace: fitDataFillAvailableSpace
    })

    if(Tabulator.moduleBindings.layout?.modes) {
        Tabulator.moduleBindings.layout.modes.fitDataFillAvailableSpace = fitDataFillAvailableSpace
    }
}


function getColumnMinWidth(column) {
    const minWidthCandidate = column.definition.minWidth ?? column.minWidth
    const minWidth = Number.parseInt(minWidthCandidate, 10)
    return Number.isFinite(minWidth) ? minWidth : 0
}


function fitDataFillAvailableSpace(columns, forced) {
    let tableWidth = this.table.rowManager.element.clientWidth
    const responsiveEnabled = this.table.options.responsiveLayout && this.table.modExists("responsiveLayout", true)

    // match fitData behavior: refresh measured data widths only when forced
    if(forced) {
        this.table.columnManager.renderer.reinitializeColumnWidths(columns)
    }

    if(responsiveEnabled) {
        this.table.modules.responsiveLayout.update()
    }

    // keep width math aligned with fitColumns when vertical scrollbar is present
    if(this.table.rowManager.element.scrollHeight > this.table.rowManager.element.clientHeight) {
        tableWidth -= this.table.rowManager.element.offsetWidth - this.table.rowManager.element.clientWidth
    }

    const visibleColumns = []
    let naturalWidth = 0

    columns.forEach((column) => {
        const wasStretchedByThisMode = Boolean(column.modules?.[STRETCHED_WIDTH_MODULE_KEY])
        if(wasStretchedByThisMode) {
            column.modules[STRETCHED_WIDTH_MODULE_KEY] = false
        }

        if(!forced && wasStretchedByThisMode) {
            // called on resize if column was stretched by this mode
            column.reinitializeWidth()
        }

        const isVisible = this.table.options.responsiveLayout
            ? column.modules.responsive.visible
            : column.visible

        if(!isVisible) {
            return
        }

        const minWidth = getColumnMinWidth(column)
        const width = Math.max(column.getWidth(), minWidth)
        const isFitDataColumn = Boolean(column.definition[KEEP_DATA_WIDTH_OPTION])

        if(column.getWidth() < width) {
            column.setWidth(width)
        }

        visibleColumns.push({
            column: column,
            width: width,
            grow: column.definition.widthGrow || 1,
            stretchable: !isFitDataColumn,
        })
        naturalWidth += width
    })

    // data overflows: keep natural fitData widths so horizontal scrollbar can appear
    if(naturalWidth >= tableWidth || !visibleColumns.length) {
        return
    }

    const freeSpace = tableWidth - naturalWidth
    const stretchableColumns = visibleColumns.filter((item) => item.stretchable)
    distributeExtraWidth(stretchableColumns, freeSpace)
}

function distributeExtraWidth(columns, freeSpace) {
    if(freeSpace <= 0 || !columns.length) {
        return
    }

    let remainingSpace = freeSpace
    let growableColumns = columns.slice()

    while(remainingSpace > 0 && growableColumns.length) {
        let totalGrowUnits = 0
        growableColumns.forEach((item) => {
            totalGrowUnits += item.grow
        })

        if(totalGrowUnits <= 0) {
            break
        }

        let distributed = 0
        const nextGrowableColumns = []

        growableColumns.forEach((item) => {
            const maxWidth = item.column.definition.maxWidth
            const requestedExtra = Math.floor((remainingSpace * item.grow) / totalGrowUnits)
            const room = typeof maxWidth === "number" ? Math.max(0, maxWidth - item.width) : Infinity
            const extra = Math.min(requestedExtra, room)

            if(extra > 0) {
                item.width += extra
                item.column.setWidth(item.width)
                item.column.modules[STRETCHED_WIDTH_MODULE_KEY] = true
                distributed += extra
            }

            if(room > extra) {
                nextGrowableColumns.push(item)
            }
        })

        if(distributed === 0) {
            break
        }

        remainingSpace -= distributed
        growableColumns = nextGrowableColumns
    }

    if(remainingSpace > 0 && growableColumns.length) {
        for(const item of growableColumns) {
            const maxWidth = item.column.definition.maxWidth
            const room = typeof maxWidth === "number" ? Math.max(0, maxWidth - item.width) : Infinity
            if(room <= 0) {
                continue
            }

            const extra = Math.min(remainingSpace, room)
            item.width += extra
            item.column.setWidth(item.width)
            item.column.modules[STRETCHED_WIDTH_MODULE_KEY] = true
            remainingSpace -= extra

            if(remainingSpace <= 0) {
                break
            }
        }
    }
}
