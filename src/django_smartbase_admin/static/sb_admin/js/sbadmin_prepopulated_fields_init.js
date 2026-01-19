'use strict';

{
    function init_prepopulate(container) {
        const $ = django.jQuery;
        const scripts = container.querySelectorAll('script[id^="sbadmin_prepopulated_fields_"][type="application/json"]');
        for (const el of scripts) {
            let fields = [];
            try {
                fields = JSON.parse(el.textContent);
            } catch (e) {
                fields = [];
            }
            for (const f of fields) {
                $(f.id).data('dependency_list', f.dependency_list).prepopulate(f.dependency_ids, f.maxLength, f.allowUnicode);
            }
        }
        return true;
    }

    init_prepopulate(document);
}


