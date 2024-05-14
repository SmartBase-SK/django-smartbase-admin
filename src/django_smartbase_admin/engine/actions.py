from django.core.exceptions import ImproperlyConfigured
from django.utils.text import slugify


class SBAdminCustomAction(object):
    title = None
    url = None
    view = None
    action_id = None
    css_class = None
    no_params = False
    open_in_modal = False

    def __init__(
        self,
        title,
        url=None,
        view=None,
        action_id=None,
        action_modifier=None,
        css_class=None,
        no_params=False,
        open_in_modal=False,
        group=None,
    ) -> None:
        super().__init__()

        if not (url or (view and action_id)):
            raise ImproperlyConfigured(
                "You must provide either url or view and action_id"
            )

        self.title = title
        self.url = url
        self.view = view
        self.action_id = action_id
        self.action_modifier = action_modifier
        self.css_class = css_class
        self.no_params = no_params
        self.open_in_modal = open_in_modal
        self.group = group
        if not url and not action_modifier:
            self.url = self.view.get_action_url(self.action_id)
        if not url and action_modifier is not None:
            self.url = self.view.get_action_url(self.action_id, action_modifier)


class SBAdminAction(object):
    view = None
    threadsafe_request = None

    def __init__(self, view, request) -> None:
        super().__init__()
        self.view = view
        self.threadsafe_request = request
