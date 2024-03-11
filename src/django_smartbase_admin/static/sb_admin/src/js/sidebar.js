export default class Sidebar {
    constructor() {
        this.sidebarActive = false
        this.scrollbarWidth = this.getScrollbarWidth()

        document.addEventListener('click', (event) => {
            this.initSidebars(event)
        })
    }

    getScrollbarWidth() {
        const scrollDiv = document.createElement('div')
        scrollDiv.className = 'scrollbar-measure'
        document.body.appendChild(scrollDiv)

        // Get the scrollbar width
        const scrollbarWidth = scrollDiv.offsetWidth - scrollDiv.clientWidth

        // Delete the div
        document.body.removeChild(scrollDiv)
        return scrollbarWidth
    }

    initSidebars(event) {
        const el = event.target.closest('.js-sidebar-toggle')
        if(el?.dataset.sidebarTarget) {
            const sidebar = document.getElementById(el.dataset.sidebarTarget)
            if(this.sidebarActive) {
                this.closeSidebar(sidebar)
            } else {
                this.openSidebar(sidebar)
            }
            event.stopPropagation()
        }
    }

    openSidebar(sidebar) {
        this.bodyAddNoScroll()
        sidebar.classList.add('active')
        this.sidebarActive = true
    }

    closeSidebar(sidebar) {
        this.bodyRemoveNoScroll()
        sidebar.classList.remove('active')
        this.sidebarActive = false
    }

    bodyAddNoScroll() {
        document.body.setAttribute('style', `overflow:hidden;padding-right:${this.scrollbarWidth}px;`)
    }

    bodyRemoveNoScroll() {
        document.body.setAttribute('style', '')
    }
}