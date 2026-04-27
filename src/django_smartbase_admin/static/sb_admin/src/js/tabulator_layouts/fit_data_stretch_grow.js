// Custom fitDataStretch variant: stretch the column marked with widthGrow instead of the last column.
// See https://github.com/olifolkerd/tabulator/issues/2725 and Tabulator's fitDataStretch layout.
export function registerFitDataStretchGrowLayout(Tabulator, tabulatorOptions) {
    if(tabulatorOptions.layout !== "fitDataStretchGrow") {
        return
    }

    Tabulator.extendModule("layout", "modes", {
        fitDataStretchGrow: fitDataStretchGrow
    })

    if(Tabulator.moduleBindings.layout?.modes) {
        Tabulator.moduleBindings.layout.modes.fitDataStretchGrow = fitDataStretchGrow
    }
}


function fitDataStretchGrow(columns) {
    let colsWidth = 0,
        tableWidth = this.table.rowManager.element.clientWidth,
        gap = 0,
        lastCol = false,
        stretchCol = false

    columns.forEach((column) => {
        if(column.modules.fitDataStretchGrowWidth) {
            column.widthFixed = false
            column.modules.fitDataStretchGrowWidth = false
        }

        if(column.widthFixed && typeof column.definition.width === "undefined") {
            column.widthFixed = false
        }

        if(!column.widthFixed) {
            column.reinitializeWidth()
        }

        if(this.table.options.responsiveLayout ? column.modules.responsive.visible : column.visible) {
            lastCol = column
            if(column.definition.widthGrow) {
                stretchCol = column
            }
        }

        if(column.visible) {
            colsWidth += column.getWidth()
        }
    })

    const targetCol = stretchCol || lastCol

    if(targetCol) {
        gap = tableWidth - colsWidth + targetCol.getWidth()

        if(this.table.options.responsiveLayout && this.table.modExists("responsiveLayout", true)) {
            targetCol.setWidth(0)
            this.table.modules.responsiveLayout.update()
        }

        if(gap > 0) {
            targetCol.setWidth(gap)
            targetCol.modules.fitDataStretchGrowWidth = true
        } else {
            targetCol.reinitializeWidth()
        }
    } else if(this.table.options.responsiveLayout && this.table.modExists("responsiveLayout", true)) {
        this.table.modules.responsiveLayout.update()
    }
}
