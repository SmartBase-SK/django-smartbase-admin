class SBAdminCustomAction(object):
    title = None
    url = None
    css_class = None
    no_params = False
    open_in_modal = False

    def __init__(
        self, title, url, css_class=None, no_params=False, open_in_modal=False
    ) -> None:
        super().__init__()
        self.title = title
        self.url = url
        self.css_class = css_class
        self.no_params = no_params
        self.open_in_modal = open_in_modal


class SBAdminAction(object):
    view = None
    threadsafe_request = None

    def __init__(self, view, request) -> None:
        super().__init__()
        self.view = view
        self.threadsafe_request = request
