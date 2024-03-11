export const createIcon = (iconId, classes = ['w-24', 'h-24']) => {
    const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svgEl.classList.add(...classes)
    const useEl = document.createElementNS('http://www.w3.org/2000/svg', 'use')
    useEl.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', `#${iconId}`)
    svgEl.append(useEl)
    return svgEl
}

export const getCookie = (name) => {
    let cookieValue = null
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';')
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim()
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1))
                break
            }
        }
    }
    return cookieValue
}

export const setCookie = (name, value, expiration_days) => {
    const d = new Date()
    d.setTime(d.getTime() + (expiration_days * 24 * 60 * 60 * 1000))
    let expires = "expires=" + d.toUTCString()
    document.cookie = name + "=" + value + ";" + expires + ";path=/"
}

export const getLastDays = (daysNum) => {
    const d = new Date()
    d.setDate(d.getDate() - (daysNum - 1))
    return d
}

export const getLastMonths = (monthsNum) => {
    const d = new Date()
    d.setMonth(d.getMonth() - monthsNum)
    return d
}

export const getObjectOrValue = (value) => {
    try {
        return JSON.parse(value)
    } catch (e) { /* empty */
    }
    return value
}

export const filterInputValueChangeListener = (inputSelector, callbackFunction) => {
    document.querySelectorAll(inputSelector).forEach((input) => {
        input.addEventListener('change', callbackFunction)
        input.addEventListener('SBAutocompleteChange', callbackFunction)
    })
}

export const filterInputValueChangedUtil = (field) => {
    const filterId = field.dataset.filterId || field.id
    const valueElem = document.querySelector(`#${filterId}-value`)
    if(!valueElem) {
        return
    }
    const valueOrObject = getObjectOrValue(field.value)
    if ((field.value === "" || field.value === "[]")) {
        if(field.dataset.emptyLabel) {
            valueElem.innerHTML = field.dataset.emptyLabel
        } else {
            valueElem.innerHTML = ''
        }
        return valueElem
    }
    if (typeof valueOrObject === 'object') {
        const labelArray = []
        const entries = Object.values(valueOrObject)
        let hasMaxEntries = false
        for (let [index, item] of entries.entries()) {
            if (index === window.sb_admin_const.MULTISELECT_FILTER_MAX_CHOICES_SHOWN) {
                break
            }
            if (index === window.sb_admin_const.MULTISELECT_FILTER_MAX_CHOICES_SHOWN - 2 && entries[index + 2]) {
                labelArray.push(item.label)
                hasMaxEntries = true
                break
            }
            labelArray.push(item.label)
        }
        let resultLabel = labelArray.join(', ')
        if(hasMaxEntries) {
            resultLabel = resultLabel.substring(0, resultLabel.length)
            resultLabel += `... +${entries.length - window.sb_admin_const.MULTISELECT_FILTER_MAX_CHOICES_SHOWN + 1}`
        }
        valueElem.innerHTML = resultLabel
    } else {
        try {
            // select
            valueElem.innerHTML = field.options[field.selectedIndex].text
        } catch (e) {
            const label = document.querySelector(`label[for=${field.id}]`)
            if(label) {
                valueElem.innerHTML = label.innerText
            } else {
                const radioLabel = document.querySelector(`label[for=${field.id}_${field.value}]`)
                if (radioLabel) {
                    valueElem.innerHTML = radioLabel.innerText
                } else {
                    valueElem.innerHTML = valueOrObject
                }
            }
        }
    }
    return valueElem
}
