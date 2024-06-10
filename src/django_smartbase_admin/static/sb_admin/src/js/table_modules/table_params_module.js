import {createIcon} from "../utils"
import {SBAdminTableModule} from "./base_module"

export class TableParamsModule extends SBAdminTableModule {
    loadFromUrl() {
        const params = this.table.getParamsFromUrl()
        const tableParams = params[this.table.constants.TABLE_PARAMS_NAME]

        let newSort = this.table.tableInitialSort
        let newPage = this.table.tableInitialPage
        let newPageSize = this.table.tableInitialPageSize

        if (tableParams) {
            newSort = tableParams[this.table.constants.TABLE_PARAMS_SORT_NAME] || newSort
            newPage = tableParams['page'] || newPage
            newPageSize = tableParams['size'] || newPageSize
        }

        newSort = this.getSortDataFromSorters(newSort)

        if (this.table.tabulator) {
            this.table.tabulator.modules.sort.setSort(newSort)
            this.table.tabulator.modules.page.size = newPageSize
            this.table.tabulator.modules.page.page = newPage
        } else {
            this.table.tableInitializeSort = newSort
            this.table.tableInitializePage = newPage
            this.table.tableInitializePageSize = newPageSize
        }
    }

    getSortDataFromSorters(sorters) {
        let sortParams = []
        sorters?.forEach((param) => {
            sortParams.push({column: param['field'] || param['column']['field'], dir: param['dir']})
        })
        return sortParams
    }

    getUrlParams() {
        const params = {}
        const tableParams = {}
        if (this.table.lastTableParams[this.table.constants.TABLE_PARAMS_SIZE_NAME] !== this.table.tableInitialPageSize) {
            tableParams[this.table.constants.TABLE_PARAMS_SIZE_NAME] = this.table.lastTableParams[this.table.constants.TABLE_PARAMS_SIZE_NAME]
        }
        if (this.table.lastTableParams[this.table.constants.TABLE_PARAMS_PAGE_NAME] !== this.table.tableInitialPage) {
            tableParams[this.table.constants.TABLE_PARAMS_PAGE_NAME] = this.table.lastTableParams[this.table.constants.TABLE_PARAMS_PAGE_NAME]
        }
        const newSort = this.getSortDataFromSorters(this.table.lastTableParams[this.table.constants.TABLE_PARAMS_SORT_NAME])
        const oldSort = this.getSortDataFromSorters(this.table.tableInitialSort)
        if (newSort.length > 0 && JSON.stringify(newSort) !== JSON.stringify(oldSort)) {
            tableParams[this.table.constants.TABLE_PARAMS_SORT_NAME] = this.table.lastTableParams[this.table.constants.TABLE_PARAMS_SORT_NAME]
        }
        if (Object.keys(tableParams).length > 0) {
            params[this.table.constants.TABLE_PARAMS_NAME] = tableParams
        }
        return params
    }

    getUrlParamsForSave() {
        const params = {}
        const tableParams = this.getUrlParams()[this.table.constants.TABLE_PARAMS_NAME]
        if (tableParams) {
            delete tableParams[this.table.constants.TABLE_PARAMS_PAGE_NAME]
            params[this.table.constants.TABLE_PARAMS_NAME] = tableParams
        }
        return params
    }

    loadFromUrlAfterInit() {
        const paginationWidget = document.querySelector(`#${this.table.paginationWidgetId}`)
        const pageSizeWidget = document.querySelector(`#${this.table.pageSizeWidgetId}`)

        this.createPagination(paginationWidget)
        this.createPageSize(pageSizeWidget)
        this.table.tabulator.on("dataProcessed", () => {
            this.createPagination(paginationWidget)
            this.createPageSize(pageSizeWidget)
        })
    }

    createPaginationButton(innerElement, clickHandler, active) {
        const button = document.createElement('button')
        if(innerElement instanceof Node) {
            button.appendChild(innerElement)
        }
        else {
            button.innerHTML = innerElement
        }

        button.type = "button"
        button.classList.add('tabulator-page')

        if(clickHandler) {
            button.onclick = clickHandler
            if(active) {
                button.classList.add('active')
            }
            return button
        }
        button.disabled = true
        return button
    }

    createPaginationButtonsFromRange(range, mapFunction, paginationWrapper, currentPage) {
        Array.from({length: range}, mapFunction).forEach((pageNum) => {
            paginationWrapper.appendChild(
                this.createPaginationButton(
                    pageNum,
                    () => {
                        this.table.tabulator.setPage(pageNum)
                    },
                    pageNum === currentPage
                )
            )
        })
    }

    createPagination(paginationWidget) {
        const maxPage = this.table.tabulator.getPageMax()
        const currentPage = this.table.tabulator.getPage()
        const currentPageSize = this.table.tabulator.getPageSize()

        paginationWidget.innerHTML = ''
        const paginationText = document.createElement('div')
        paginationText.classList.add('max-xs:text-12')
        const dataCount = this.table.tabulator.getDataCount()
        if(dataCount > 0) {
            const from = (currentPageSize * (currentPage - 1)) + 1
            const to = currentPageSize === dataCount ? currentPageSize * currentPage : currentPageSize * (currentPage - 1) + this.table.tabulator.getDataCount()
            paginationText.innerHTML = window.sb_admin_translation_strings["page"].replace('${from}', from).replace('${to}', to).replace('${total}', this.table.tabulator.modules.page.remoteRowCountEstimate)
        }
        else {
            paginationText.innerHTML = window.sb_admin_translation_strings["page_empty"]
        }

        paginationWidget.appendChild(paginationText)

        if(maxPage === 1) {
            return
        }

        const paginationWrapper = document.createElement('div')
        paginationWrapper.classList.add('tabulator-paginator')
        paginationWidget.appendChild(paginationWrapper)

        const prevButton = this.createPaginationButton(
            createIcon('Left', ['w-20', 'h-20']),
            () => {
                this.table.tabulator.setPage(currentPage - 1)
            }
        )
        prevButton.disabled = currentPage === 1
        paginationWrapper.appendChild(prevButton)

        const activeRange = this.table.constants.PAGINATION_ACTIVE_RANGE

        if(maxPage > activeRange + 1) {
            // with more pages than active range, split page buttons with '...'
            if(currentPage >= activeRange) {
                // create '1 ... X'
                paginationWrapper.appendChild(this.createPaginationButton(
                    1,
                    () => {
                        this.table.tabulator.setPage(1)
                    })
                )
                paginationWrapper.appendChild(
                    this.createPaginationButton(
                        createIcon('More', ['w-20', 'h-20', 'mt-8'])
                    )
                )
                if(currentPage > maxPage - activeRange + 1 ) {
                    // create '1 ... X'
                    this.createPaginationButtonsFromRange(
                        activeRange,
                        (x, i) => i + 1 + maxPage - activeRange,
                        paginationWrapper,
                        currentPage
                    )
                }
                else {
                    // create '1 ... active range buttons ... X'
                    this.createPaginationButtonsFromRange(
                        activeRange,
                        (x, i) => i + currentPage - Math.floor(activeRange  / 2),
                        paginationWrapper,
                        currentPage
                    )
                    paginationWrapper.appendChild(
                        this.createPaginationButton(
                            createIcon('More', ['w-20', 'h-20', 'mt-8'])
                        )
                    )
                    paginationWrapper.appendChild(this.createPaginationButton(
                        maxPage,
                        () => {
                            this.table.tabulator.setPage(maxPage)
                        })
                    )
                }
            }
            else {
                // create 'active range buttons ... X'
                this.createPaginationButtonsFromRange(
                    activeRange,
                    (x, i) => i + 1,
                    paginationWrapper,
                    currentPage
                )
                paginationWrapper.appendChild(
                    this.createPaginationButton(
                        createIcon('More', ['w-20', 'h-20', 'mt-8'])
                    )
                )
                paginationWrapper.appendChild(this.createPaginationButton(
                    maxPage,
                    () => {
                        this.table.tabulator.setPage(maxPage)
                    })
                )
            }
        }
        else {
            this.createPaginationButtonsFromRange(
                maxPage,
                (x, i) => i + 1,
                paginationWrapper,
                currentPage
            )
        }


        const nextButton = this.createPaginationButton(
            createIcon('Right', ['w-20', 'h-20']),
            () => {
                this.table.tabulator.setPage(currentPage + 1)
            }
        )
        nextButton.disabled = currentPage === maxPage
        paginationWrapper.appendChild(nextButton)
    }

    createPageSize(pageSizeWidget) {
        pageSizeWidget.innerHTML = ''
        const pageSizeWrapper = document.createElement('div')
        pageSizeWrapper.classList.add('relative')
        const pageSizeDropdownContent = document.createElement('ul')
        pageSizeDropdownContent.classList.add('dropdown-menu', 'dropdown-menu-end')
        pageSizeDropdownContent.style.maxWidth = '120px'

        this.table.constants.PAGE_SIZE_OPTIONS.forEach((pageSize) => {
            const pageSizeEl = document.createElement('li')
            pageSizeEl.classList.add('dropdown-menu-link')
            pageSizeEl.innerHTML = pageSize
            pageSizeEl.onclick = () => {
                this.table.tabulator.setPageSize(pageSize)
            }
            pageSizeDropdownContent.appendChild(pageSizeEl)
        })

        pageSizeWrapper.appendChild(this.createPageSizeDropdownButton(this.table.tabulator.getPageSize()))
        pageSizeWrapper.appendChild(pageSizeDropdownContent)
        pageSizeWidget.appendChild(pageSizeWrapper)
    }

    createPageSizeDropdownButton(currentPageSize) {
        const pageSizeButton = document.createElement('button')
        pageSizeButton.type = "button"
        pageSizeButton.classList.add('btn', 'px-10', 'font-normal', 'sm:min-w-84')
        pageSizeButton.setAttribute('data-bs-toggle', 'dropdown')
        pageSizeButton.setAttribute('aria-expanded', 'false')
        pageSizeButton.setAttribute('data-bs-offset', '[0,8]')

        const pageSizeEl = document.createElement('span')
        pageSizeEl.innerHTML = currentPageSize

        pageSizeButton.appendChild(pageSizeEl)
        pageSizeButton.appendChild(createIcon('Down',['w-20', 'h-20', 'ml-8']))

        return pageSizeButton
    }
}
