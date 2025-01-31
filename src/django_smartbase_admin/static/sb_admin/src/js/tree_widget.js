const loadValue = function ($inputEl, treeWidgetData, treeInstance) {
    let value = $inputEl.val()
    if (value !== undefined) {
        treeInstance.selectAll(false)
    }

    let selectedKeys = [value]
    if (treeWidgetData.filter === true) {
        let selectedData = []
        selectedKeys = []
        try {
            selectedData = JSON.parse(value)
        } catch(e) {
            selectedData = []
        }
        finally {
            selectedData.forEach(function (item) {
                selectedKeys.push(item.value)
            })
        }
    } else if (treeWidgetData.multiselect === 2) {
        try {
            selectedKeys = JSON.parse(value)
        } catch (e) {
            selectedKeys = []
        }
    }
    selectedKeys.forEach(function (key) {
        let selectedNode = treeInstance.getNodeByKey(key)
        if (selectedNode) {
            selectedNode.getParentList().forEach(function (node) {
                // Expand all parents of selected node
                node.setExpanded(true)
            })
            selectedNode.setSelected(true)
        }
    })
}


'use strict'
{
    $(function () {
        const initTree = function ($treeEl) {
            if ($treeEl.hasClass('fancytree-container')) {
                return
            }
            $treeEl.on('change', (e) => {
                const changeTarget = e.target.dataset['changeTarget']
                if(changeTarget) {
                    const changeTargetEl = document.querySelector(changeTarget)
                    if(changeTargetEl) {
                        changeTargetEl.value = e.target.value
                    }
                }
            })
            const $treeDataEl = $('#' + $treeEl.data('tree-data-id'))
            const $treeAdditionalColumnsDataEl = $('#' + $treeEl.data('tree-additional-columns-id'))
            const $treeStringsDataEl = $('#' + $treeEl.data('tree-strings-id'))
            let treeWidgetData = {}
            let additionalColumns = []
            let treeStrings = {loading: "Loading...", loadError: "Load error!", moreData: "More...", noData: "No data."}
            try {
                treeWidgetData = JSON.parse($treeDataEl.text()) || {}
                additionalColumns = JSON.parse($treeAdditionalColumnsDataEl.text()) || []
                treeStrings = JSON.parse($treeStringsDataEl.text())
            } catch (e) {
                console.error(e)
            }
            const $inputEl = $('#' + treeWidgetData.input_id)
            const $searchEl = $('#' + treeWidgetData.input_id + '_search')
            const $matchesEl = $('#' + treeWidgetData.input_id + '_matches')
            const $label = $('#' + treeWidgetData.input_id + '_label')
            const tableConfig = {
                indentation: 32,
                nodeColumnIdx: 0,
            }
            if (treeWidgetData.checkbox) {
                tableConfig.checkboxColumnIdx = 0
                tableConfig.nodeColumnIdx = 1
            }
            let extensions = ["table", "gridnav", "filter"]
            if (treeWidgetData.reorder_url) {
                extensions.push("dnd5")
            }
            $treeEl.fancytree({
                source: {
                    url: treeWidgetData.data_url,
                },
                extensions: extensions,
                checkbox: treeWidgetData.checkbox,
                selectMode: treeWidgetData.multiselect,
                dnd5: {
                    preventVoidMoves: true,
                    preventRecursion: true,
                    autoExpandMS: 400,
                    dragStart: function () {
                        return true
                    },
                    dragEnter: function () {
                        return true
                    },
                    dragDrop: function (node, data) {
                        data.otherNode.moveTo(node, data.hitMode)
                    },
                },
                filter: {
                    autoApply: true,   // Re-apply last filter if lazy data is loaded
                    autoExpand: true, // Expand all branches that contain matches while filtered
                    counter: false,     // Show a badge with number of matching child nodes near parent icons
                    fuzzy: true,      // Match single characters in order, e.g. 'fb' will match 'FooBar'
                    hideExpandedCounter: true,  // Hide counter badge if parent is expanded
                    hideExpanders: true,       // Hide expanders if all child nodes are hidden by filter
                    highlight: true,   // Highlight matches by wrapping inside <mark> tags
                    leavesOnly: false, // Match end nodes only
                    nodata: true,      // Display a 'no data' status node if result is empty
                    mode: "hide"       // Grayout unmatched nodes (pass "hide" to remove unmatched node instead)
                },
                table: tableConfig,
                gridnav: {
                    autofocusInput: false,
                    handleCursorKeys: true,
                },
                strings: treeStrings,
                postProcess: function (event, data) {
                    setTimeout(function () {
                        loadValue($inputEl, treeWidgetData, data.tree)
                    }, 1)
                },
                select: function (event, data) {
                    let value = null
                    if (treeWidgetData.filter) {
                        value = data.tree.getSelectedNodes().map(function (node) {
                            return {'value': node.key, 'label': node.title}
                        })
                        $inputEl[0].value = JSON.stringify(value)
                    } else {
                        value = data.tree.getSelectedNodes().map(function (node) {
                            return node.key
                        }).join(", ")
                        if (treeWidgetData.multiselect === 2) {
                            value = JSON.stringify(data.tree.getSelectedNodes().map(function (node) {
                                return node.key
                            }))
                        }
                        let label = data.tree.getSelectedNodes().map(function (node) {
                            return node.title
                        }).join(", ")
                        $label.text(label)
                        $inputEl.val(value)
                    }
                    $inputEl[0].dispatchEvent(new CustomEvent('SBAutocompleteChange'))
                    $inputEl[0].dispatchEvent(new Event('change', {bubbles: true}))
                },
                renderNode: function (event, data) {
                    const reorderActive = treeWidgetData.reorder_url
                    const nodeRendered = data.node.rendered
                    const filteringActive = data.node.tree.enableFilter
                    const detailUrlPresent = treeWidgetData.detail_url
                    const validVisibleNode = data.node.span && data.node.span.classList.contains("fancytree-node") && !data.node.tr.classList.contains("fancytree-hide")
                    if (detailUrlPresent && (!nodeRendered || filteringActive) && !reorderActive && validVisibleNode) {
                        const title = data.node.span.querySelector('.fancytree-title')
                        const titleLink = document.createElement('a')
                        titleLink.innerHTML = title.innerHTML
                        titleLink.classList.add('link')
                        title.innerHTML = ''
                        title.append(titleLink)
                        title.addEventListener('mousedown', function (e) {
                            e.preventDefault()
                            e.stopPropagation()
                            const url = treeWidgetData.detail_url.replace(-1, data.node.key)
                            if(e.button === 0) {
                                window.location = url
                                return
                            }
                            if(e.button === 1) {
                                window.open(url)
                            }
                        }, true)
                    }
                    if (nodeRendered && !reorderActive) {
                        return
                    }
                    let isLastSib = data.node && data.node.tr && data.node.tr.classList.contains('fancytree-lastsib')
                    isLastSib = isLastSib === undefined ? false : isLastSib
                    if (data.node.parent) {
                        data.node.treeLevel = data.node.parent.treeLevel + 1
                        data.node.treeAdditionalLevel = [{
                            level: data.node.treeLevel,
                            lastSib: isLastSib
                        }, ...data.node.parent.treeAdditionalLevel]
                    } else {
                        data.node.treeLevel = 0
                        data.node.treeAdditionalLevel = []
                    }
                    data.node.rendered = true
                    if (validVisibleNode) {
                        const expander = data.node.span.querySelector('.fancytree-expander')
                        const level = data.node.treeLevel
                        const additionalLevel = data.node.treeAdditionalLevel
                        expander.innerHTML = ""
                        expander.className = 'fancytree-expander'
                        expander.classList.add('level-' + level)
                        if (data.node.parent.expanded) {
                            expander.classList.add('expanded-parent')
                        }
                        additionalLevel.forEach((item, i) => {
                            if (i !== 0 && item.lastSib) {
                                return
                            }
                            const expanderAdditional = document.createElement('span')
                            expanderAdditional.classList.add('expander-additional')
                            if (i === 0) {
                                expanderAdditional.classList.add('expander-additional-last')
                            }
                            expanderAdditional.style.left = -(50 + 100 * i) + '%'
                            expander.append(expanderAdditional)
                        })
                        const expanderBorder = document.createElement('span')
                        expanderBorder.classList.add('expander-border')
                        expander.append(expanderBorder)
                        expander.append(document.createElement('div'))
                    }
                },
                renderColumns: function (event, data) {
                    const $tdList = $(data.node.tr).find(">td")
                    additionalColumns.forEach(function (column, index) {
                        let value = data.node.data[column.key]
                        if (column.hide_zero && value === 0) {
                            value = ""
                        }
                        $tdList.eq(1 + tableConfig.nodeColumnIdx + index).html(value)
                    })
                },
            })

            const clearSearchInput = function () {
                $searchEl.val("")
                $matchesEl.text("")
                treeInstance.visit(function (node) {
                    node.rendered = false
                })
                treeInstance.clearFilter()
            }

            const treeInstance = $.ui.fancytree.getTree('#' + treeWidgetData.input_id + '_tree')
            $inputEl.on('SBTableFilterFormLoad', () => {
                loadValue($inputEl, treeWidgetData, treeInstance)
            })
            $inputEl.on('clear', () => {
                treeInstance.getSelectedNodes().map(node => {
                    node.setSelected(false)
                })
            })
            $searchEl.on("keyup", function (e) {
                let match = $(this).val()
                let n = treeInstance.filterNodes(match)

                if (e && e.which === $.ui.keyCode.ESCAPE || $.trim(match) === "") {
                    clearSearchInput()
                    return
                }
                $matchesEl.text("(" + n + " matches)")
            }).trigger("focus")

            $searchEl.on('search', function (e) {
                // handle clear event of search input only if clicked on X
                if (e.target.value) {
                    return
                }
                clearSearchInput()
            })

            treeInstance.saveTreeOrder = function () {
                const order = JSON.stringify(treeInstance.toDict())
                fetch(treeWidgetData.reorder_url, {
                    method: 'POST',
                    headers: {
                        "X-CSRFToken": window.csrf_token,
                    },
                    body: order
                }).then(response => response.json())
                    .then(res => {
                        document.getElementById("notification-messages").innerHTML = res.messages
                        window.htmx.process(document.getElementById("notification-messages"))
                    })
            }
        }

        const initAllTrees = function () {
            $('.js-tree-widget').each(function (index, element) {
                const $treeEl = $(element)
                if ($treeEl.hasClass('fancytree-container')) {
                    return
                }
                const $dropdownMenu = $treeEl.closest('.dropdown-menu')
                if ($dropdownMenu.length > 0) {
                    const initTreeOnShow = function () {
                        initTree($treeEl)
                        $dropdownMenu.prev().off('show.bs.dropdown', initTreeOnShow)
                    }
                    $dropdownMenu.prev().on('show.bs.dropdown', initTreeOnShow)
                    return
                }
                initTree($treeEl)
            })
        }
        initAllTrees()

        document.addEventListener('formset:added', () => {
            initAllTrees()
        })

        const queryBuilderEl$ = $(".query-builder-advanced")
        queryBuilderEl$.on("afterCreateRuleInput.queryBuilder", function () {
            setTimeout(() => {
                //next tick
                initAllTrees()
            }, 0)
        })
    })
}
