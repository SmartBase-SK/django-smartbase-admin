from django.core.exceptions import ImproperlyConfigured


class SBAdminCustomAction(object):
    title = None
    url = None
    view = None
    action_id = None
    action_modifier = None
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
        self.title = title
        self.url = url
        self.view = view
        self.action_id = action_id
        self.action_modifier = action_modifier
        self.css_class = css_class
        self.no_params = no_params
        self.open_in_modal = open_in_modal
        self.group = group
        self.resolve_url()

    def resolve_url(self):
        if not (self.url or (self.view and self.action_id)):
            raise ImproperlyConfigured(
                "You must provide either url or view and action_id"
            )

        if not self.url and not self.action_modifier:
            self.url = self.view.get_action_url(self.action_id)
        if not self.url and self.action_modifier is not None:
            self.url = self.view.get_action_url(self.action_id, self.action_modifier)


class SBAdminFormViewAction(SBAdminCustomAction):
    def __init__(self, target_view, *args, **kwargs) -> None:
        self.target_view = target_view
        super().__init__(*args, **kwargs)

    def resolve_url(self):
        """
        self.url and self.action_id is resolved in side django_smartbase_admin.engine.admin_base_view.SBAdminBaseView.process_actions
        """
        pass
