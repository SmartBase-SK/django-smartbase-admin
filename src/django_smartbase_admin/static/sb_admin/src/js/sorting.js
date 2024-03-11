import Sortable, { Swap } from 'sortablejs'
Sortable.mount(new Swap())

export default class Sorting {
    constructor() {
        this.sortableOptions = {
            handle: '.js-drag-handle',
            animation: 150,
            ghostClass: 'bg-primary-50',
            swap: true,
            swapClass: 'bg-primary-50',
            onUpdate: this.handleSortableUpdate.bind(this),
            onAdd: this.handleSortableUpdate.bind(this)
        }
        this.lists = []
        this.initSortable()
        this.initHtmxListeners()
    }

    initSortable() {
        document.querySelectorAll('.js-sortable-list').forEach(list => {
            this.lists.push(new Sortable(list, this.sortableOptions))
        })
    }

    initHtmxListeners() {
        document.body.addEventListener('htmx:beforeSwap', ()=>{
            this.lists.forEach(list => {
                if(list.el) {
                    list.destroy()
                }
            })
            this.lists = []
        })

        document.body.addEventListener('htmx:afterSwap', ()=>{
            this.initSortable()
        })
    }

    handleSortableUpdate(e) {
        // TODO
        console.log(e)
    }
}