/*
How to use:
- Modal is triggered by element with data attribute [data-show-confirm]
- Modal emits events if closed:
--- event 'cancel' is dispatched by clicking on Cancel or X button
--- event 'confirm' is dispatched by clicking on Submit button
--- element which dispatch the event is defined by 'data-response-target' attribute of 'js-confirmation' element, default is 'body'
--- the event can be used to trigger htmx request with 'hx-trigger' e.g. hx-trigger="confirm from:body" for default value of data-response-target
- 'js-confirmation' element can also define Header and Body of confirmation modal with data-confirm-header and data-confirm-body attributes
 */

export class Confirmation {
    constructor() {
        this.modalEl = document.getElementById('confirmation-modal')
        if(!this.modalEl) {
            return
        }
        this.modal = new window.bootstrap5.Modal(this.modalEl)

        this.defaultModalData = {
            'responseTarget': 'body',
            'confirmBody': null,
            'confirmIcon': null,
            'confirmFooter': null,
            'confirmSubmit': 'Confirm',
            'confirmClose': 'Cancel',
            'submitEvent': 'confirm',
            'cancelEvent': 'cancel',
        }

        this.modalEl.addEventListener('click', event => {
            const closingOrSubmittingButton = event.target.closest('.js-modal-close')
            if(closingOrSubmittingButton) {
                let eventType
                let isSubmitButton = closingOrSubmittingButton.classList.contains('js-modal-submit')
                if (isSubmitButton) {
                    eventType = this.modalData.submitEvent
                } else {
                    eventType = this.modalData.cancelEvent
                }
                this.fireEventToTarget(eventType)
                this.modal.hide()
            }
        })

        document.addEventListener('click', event => {
            const confirmationButton = event.target.closest('[data-show-confirm]')
            if (confirmationButton) {
                this.updateModalData(confirmationButton)
                this.updateModalContent()
                this.modal.show()
            }
        })
    }

    fireEventToTarget(eventType) {
        const target = document.querySelector(this.modalData.responseTarget)
        const event = new Event(eventType)
        target.dispatchEvent(event)
    }

    updateModalData(target) {
        this.modalData = {...this.defaultModalData}
        Object.keys(this.modalData).forEach(key => {
            if(target.dataset[key]) {
                this.modalData[key] = target.dataset[key]
            }
        })
    }

    updateModalContent() {
        if(this.modalData.confirmSubmit) {
            this.modalEl.querySelector('.js-modal-submit').innerHTML = this.modalData.confirmSubmit
        }
        if(this.modalData.confirmClose) {
            this.modalEl.querySelector('.js-modal-close-button').innerHTML = this.modalData.confirmClose
        }
        if(this.modalData.confirmBody) {
            this.modalEl.querySelector('.js-modal-body').innerHTML = this.modalData.confirmBody
        }
        if(this.modalData.confirmIcon) {
            this.modalEl.querySelector('.js-modal-icon').innerHTML = this.modalData.confirmIcon
        }
        if(this.modalData.confirmFooter) {
            this.modalEl.querySelector('.js-modal-footer').innerHTML = this.modalData.confirmFooter
        }
    }
}

window.ConfirmationClass = Confirmation

window.addEventListener("DOMContentLoaded", () => {
    window.Confirmation = new Confirmation()
})
