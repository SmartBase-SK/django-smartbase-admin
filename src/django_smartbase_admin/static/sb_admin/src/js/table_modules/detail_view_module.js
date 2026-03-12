import {SBAdminTableModule} from "./base_module"


export class DetailViewModule extends SBAdminTableModule {

    getDetailUrl(row) {
        return this.table.tableDetailUrl.replace(this.table.constants.OBJECT_ID_PLACEHOLDER, row.getData()[this.table.tableIdColumnName]) + '?_changelist_filters=' + encodeURIComponent(this.table.getUrlParamsString().replace('?' + this.table.constants.BASE_PARAMS_NAME + '=', '' + this.table.constants.BASE_PARAMS_NAME + '='))
    }

    afterInit() {
        // Handle middle mouse button clicks via mousedown to prevent browser scroll
        this.table.tabulator.element.addEventListener("mousedown", (e) => {
            // Check if middle mouse button (button === 1) and prevent default scroll behavior
            if (e.button === 1) {
                const rowElement = e.target.closest(".tabulator-row")
                if (rowElement && !e.target.closest(".row-select-wrapper") && !e.target.closest(".row-prevent-click")) {
                    e.preventDefault()
                }
            }
        }, true) // Use capture phase to catch event early

        // Handle auxclick event (modern way to handle middle/right mouse clicks)
        // This is the proper event for middle clicks and preserves user-initiated context
        this.table.tabulator.element.addEventListener("auxclick", (e) => {
            // Check if middle mouse button (button === 1)
            if (e.button === 1) {
                const rowElement = e.target.closest(".tabulator-row")
                if (rowElement && !e.target.closest(".row-select-wrapper") && !e.target.closest(".row-prevent-click")) {
                    e.preventDefault()
                    e.stopPropagation()
                    
                    // Find the row by matching the element
                    const rows = this.table.tabulator.getRows()
                    let row = null
                    for (let i = 0; i < rows.length; i++) {
                        if (rows[i].getElement() === rowElement) {
                            row = rows[i]
                            break
                        }
                    }
                    
                    if (row) {
                        // Use window.open directly - browsers may focus new tabs, but this is the most reliable method
                        // Note: Browser security restrictions prevent programmatic prevention of focus changes
                        window.open(this.getDetailUrl(row), '_blank', 'noopener')
                    }
                }
            }
        }, true)

        // Handle regular left clicks
        this.table.tabulator.on("rowClick", (e, row) => {
            if (e.target.closest(".row-select-wrapper") || e.target.closest(".row-prevent-click")) {
                return
            }
            // Skip if middle mouse button (already handled by mousedown/auxclick)
            if (e.button === 1 || e.which === 2) {
                return
            }
            window.location = this.getDetailUrl(row)
        })
    }
}
