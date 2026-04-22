import { SBAdminTableModule } from "./base_module"


export class StickyFooterModule extends SBAdminTableModule {

    afterInit() {
        const scrollbar = document.querySelector(
            `[data-sticky-scrollbar="${this.table.viewId}"]`
        )
        if (!scrollbar) {
            console.warn(`[StickyFooterModule] sticky scrollbar element missing for viewId: ${this.table.viewId}`)
            return
        }
        const spacer = scrollbar.firstElementChild
        const tableEl = this.table.tabulator.element
        const tableholder = tableEl.querySelector(".tabulator-tableholder")
        if (!tableholder || !spacer) {
            console.warn(`[StickyFooterModule] tableholder or spacer missing for viewId: ${this.table.viewId}`)
            return
        }

        tableholder.classList.add("tabulator-tableholder--sticky-footer")

        const syncWidth = () => {
            const contentWidth = tableholder.scrollWidth
            spacer.style.width = `${contentWidth}px`
            // +1 absorbs sub-pixel rounding that would otherwise flag a non-overflowing table as overflowing
            const overflows = contentWidth > tableholder.clientWidth + 1
            scrollbar.toggleAttribute("data-no-overflow", !overflows)
            if (!overflows) {
                scrollbar.scrollLeft = 0
            }
        }

        tableholder.addEventListener("scroll", () => {
            if (scrollbar.scrollLeft !== tableholder.scrollLeft) {
                scrollbar.scrollLeft = tableholder.scrollLeft
            }
        }, { passive: true })

        scrollbar.addEventListener("scroll", () => {
            if (tableholder.scrollLeft !== scrollbar.scrollLeft) {
                tableholder.scrollLeft = scrollbar.scrollLeft
            }
        }, { passive: true })

        const resizeObserver = new ResizeObserver(syncWidth)
        resizeObserver.observe(tableholder)
        const innerTable = tableholder.querySelector(".tabulator-table")
        if (innerTable) {
            resizeObserver.observe(innerTable)
        }

        this.table.tabulator.on("dataProcessed", syncWidth)
        this.table.tabulator.on("columnResized", syncWidth)
        this.table.tabulator.on("columnVisibilityChanged", syncWidth)

        syncWidth()
    }
}
