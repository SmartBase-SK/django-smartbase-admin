import { SBAdminTableModule } from "./base_module"


export class DataTreeModule extends SBAdminTableModule {

    freezeTableHeight() {
        this.table.tabulator.element.style.height = `${this.table.tabulator.element.offsetHeight}px`
    }

    restoreTableHeight() {
        requestAnimationFrame(() => {
            this.table.tabulator.element.style.height = this.table.tabulator.options.height
        })
    }

    modifyTabulatorOptions(tabulatorOptions) {
        const lastChildField = tabulatorOptions['sbadminTreeLastChildField']
        if (!tabulatorOptions['dataTree'] || !lastChildField) {
            return tabulatorOptions
        }
        const existingRowFormatter = tabulatorOptions['rowFormatter']
        tabulatorOptions['rowFormatter'] = (row) => {
            row.getElement().classList.toggle(
                'tabulator-tree-child-last',
                Boolean(row.getData()?.[lastChildField]),
            )
            if (typeof existingRowFormatter === 'function') {
                existingRowFormatter(row)
            }
        }
        return tabulatorOptions
    }

    afterInit() {
        if (!this.table.tabulatorOptions['dataTree']) {
            return
        }

        this.table.tabulator.element.addEventListener('mousedown', (e) => {
            if (!e.target.closest('.tabulator-data-tree-control')) {
                return
            }
            this.freezeTableHeight()
        }, true)

        const restoreHeight = () => {
            this.restoreTableHeight()
        }

        this.table.tabulator.on("dataTreeRowExpanded", restoreHeight)
        this.table.tabulator.on("dataTreeRowCollapsed", restoreHeight)
    }
}
