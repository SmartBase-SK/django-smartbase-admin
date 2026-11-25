const SEARCH_DEBOUNCE_MS = 150
const SVG_NS = 'http://www.w3.org/2000/svg'
const XLINK_NS = 'http://www.w3.org/1999/xlink'

const isMac = () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '')

export default class QuickSearch {
    constructor() {
        this.root = document.getElementById('sb-quick-search')
        if (!this.root) {
            return
        }
        this.url = this.root.dataset.url
        this.input = this.root.querySelector('.js-quick-search-input')
        this.results = this.root.querySelector('.js-quick-search-results')
        this.clearButton = this.root.querySelector('.js-quick-search-clear')
        this.items = []
        this.activeIndex = -1
        this.timer = null
        this.controller = null
        this.lastQuery = null

        if (isMac()) {
            document.querySelectorAll('.js-quick-search-modifier').forEach((el) => {
                el.textContent = '⌘'
            })
        }
        this.bindEvents()
    }

    bindEvents() {
        document.addEventListener('keydown', (event) => {
            if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k') {
                event.preventDefault()
                this.isOpen() ? this.close() : this.open()
            }
        })
        document.querySelectorAll('.js-quick-search-open').forEach((button) => {
            button.addEventListener('click', (event) => {
                event.preventDefault()
                this.open()
            })
        })
        this.root.querySelectorAll('.js-quick-search-close').forEach((el) => {
            el.addEventListener('click', () => this.close())
        })
        this.input.addEventListener('input', () => this.scheduleSearch())
        this.input.addEventListener('keydown', (event) => this.handleKeydown(event))
        this.clearButton.addEventListener('click', () => {
            this.input.value = ''
            this.input.focus()
            this.search()
        })
        this.results.addEventListener('mousemove', (event) => {
            const item = event.target.closest('.quick-search-item')
            if (item) {
                this.setActive(Number(item.dataset.index), false)
            }
        })
    }

    isOpen() {
        return !this.root.classList.contains('hidden')
    }

    open() {
        this.root.classList.remove('hidden')
        document.body.classList.add('overflow-hidden')
        this.input.focus()
        this.input.select()
        if (this.lastQuery === null) {
            this.search()
        }
    }

    close() {
        this.root.classList.add('hidden')
        document.body.classList.remove('overflow-hidden')
    }

    handleKeydown(event) {
        if (event.key === 'Escape') {
            event.preventDefault()
            this.close()
        } else if (event.key === 'ArrowDown' || (event.key === 'Tab' && !event.shiftKey)) {
            event.preventDefault()
            this.move(1)
        } else if (event.key === 'ArrowUp' || (event.key === 'Tab' && event.shiftKey)) {
            event.preventDefault()
            this.move(-1)
        } else if (event.key === 'Enter') {
            event.preventDefault()
            this.openItem(this.activeIndex, event.metaKey || event.ctrlKey)
        }
    }

    scheduleSearch() {
        this.clearButton.classList.toggle('hidden', !this.input.value)
        clearTimeout(this.timer)
        this.timer = setTimeout(() => this.search(), SEARCH_DEBOUNCE_MS)
    }

    search() {
        const query = this.input.value.trim()
        this.clearButton.classList.toggle('hidden', !this.input.value)
        if (query === this.lastQuery) {
            return
        }
        if (this.controller) {
            this.controller.abort()
        }
        this.controller = new AbortController()
        const url = `${this.url}?q=${encodeURIComponent(query)}`
        fetch(url, {
            headers: {'X-Requested-With': 'XMLHttpRequest'},
            credentials: 'same-origin',
            signal: this.controller.signal,
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error(response.statusText)
                }
                return response.json()
            })
            .then((data) => {
                this.lastQuery = query
                this.render(data.sections || [], query)
            })
            .catch((error) => {
                if (error.name !== 'AbortError') {
                    this.render([], query)
                }
            })
    }

    render(sections, query) {
        this.results.replaceChildren()
        this.items = []
        sections.forEach((section) => {
            const sectionEl = document.createElement('div')
            sectionEl.className = 'quick-search-section'
            const title = document.createElement('div')
            title.className = 'quick-search-section-title'
            title.textContent = section.title
            sectionEl.appendChild(title)
            section.items.forEach((item) => {
                sectionEl.appendChild(this.renderItem(item, this.items.length))
                this.items.push(item)
            })
            this.results.appendChild(sectionEl)
        })
        if (!this.items.length && query) {
            const empty = document.createElement('div')
            empty.className = 'quick-search-empty'
            empty.textContent = window.sb_admin_translation_strings?.no_results || 'No results found'
            this.results.appendChild(empty)
        }
        this.setActive(this.items.length ? 0 : -1)
    }

    renderItem(item, index) {
        const link = document.createElement('a')
        link.className = 'quick-search-item'
        link.href = item.url
        link.dataset.index = String(index)
        link.setAttribute('role', 'option')
        link.id = `sb-quick-search-item-${index}`

        const iconWrap = document.createElement('span')
        iconWrap.className = 'quick-search-item-icon'
        if (item.icon) {
            const svg = document.createElementNS(SVG_NS, 'svg')
            svg.setAttribute('class', 'w-20 h-20')
            const use = document.createElementNS(SVG_NS, 'use')
            use.setAttributeNS(XLINK_NS, 'xlink:href', `#${item.icon}`)
            svg.appendChild(use)
            iconWrap.appendChild(svg)
        }
        link.appendChild(iconWrap)

        const text = document.createElement('span')
        text.className = 'quick-search-item-text'
        const title = document.createElement('span')
        title.className = 'quick-search-item-title'
        title.textContent = item.title
        text.appendChild(title)
        if (item.description) {
            const description = document.createElement('span')
            description.className = 'quick-search-item-description'
            description.textContent = item.description
            text.appendChild(description)
        }
        link.appendChild(text)
        return link
    }

    setActive(index, scroll = true) {
        const links = this.results.querySelectorAll('.quick-search-item')
        links.forEach((link) => {
            link.classList.remove('active')
            link.removeAttribute('aria-selected')
        })
        this.activeIndex = index
        const active = links[index]
        if (!active) {
            this.input.removeAttribute('aria-activedescendant')
            return
        }
        active.classList.add('active')
        active.setAttribute('aria-selected', 'true')
        this.input.setAttribute('aria-activedescendant', active.id)
        if (scroll) {
            active.scrollIntoView({block: 'nearest'})
        }
    }

    move(step) {
        if (!this.items.length) {
            return
        }
        const next = (this.activeIndex + step + this.items.length) % this.items.length
        this.setActive(next)
    }

    openItem(index, newTab) {
        const item = this.items[index]
        if (!item) {
            return
        }
        if (newTab) {
            window.open(item.url, '_blank', 'noopener')
        } else {
            window.location.href = item.url
        }
    }
}
