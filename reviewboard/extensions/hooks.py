from __future__ import unicode_literals

from djblets.extensions.hooks import (ExtensionHook, ExtensionHookPoint,
                                      TemplateHook, URLHook)
from djblets.util.compat import six

from reviewboard.attachments.mimetypes import (register_mimetype_handler,
                                               unregister_mimetype_handler)
from reviewboard.reviews.fields import (get_review_request_fieldset,
                                        register_review_request_fieldset,
                                        unregister_review_request_fieldset)

from reviewboard.reviews.ui.base import register_ui, unregister_ui


@six.add_metaclass(ExtensionHookPoint)
class DashboardHook(ExtensionHook):
    def __init__(self, extension, entries=[], *args, **kwargs):
        super(DashboardHook, self).__init__(extension, *args, **kwargs)
        self.entries = entries


@six.add_metaclass(ExtensionHookPoint)
class UserPageSidebarHook(ExtensionHook):
    """A Hook for adding entries to sidebar of /users/<user> page.

    This takes a list of entries. Each entry represents something on the
    user page and is a dictionary with the following keys:

        * ``label``:    The label to display.
        * ``url``:      The URL to point to.
        * ``subitems``: Dictionary for storing second level entries.

    ``subitems`` is another dictionary that will be indented to show a
    hierarchy of items. Each subitem is a dictionary with the following keys:

        * ``label``:    The label for the sub-entry.
        * ``url``:      The URL that the sub-entry points to.
    """
    def __init__(self, extension, entries=[], *args, **kwargs):
        super(UserPageSidebarHook, self).__init__(extension)
        self.entries = entries


@six.add_metaclass(ExtensionHookPoint)
class NavigationBarHook(ExtensionHook):
    """A hook for adding entries to the main navigation bar.

    This takes a list of entries. Each entry represents something
    on the navigation bar, and is a dictionary with the following keys:

        * ``label``:    The label to display
        * ``url``:      The URL to point to.
        * ``url_name``: The name of the URL to point to.

    Only one of ``url`` or ``url_name`` is required. ``url_name`` will
    take precedence.

    If your hook needs to access the template context, it can override
    get_entries and return results from there.
    """
    def __init__(self, extension, entries={}, *args, **kwargs):
        super(NavigationBarHook, self).__init__(extension, *args,
                                                **kwargs)
        self.entries = entries

    def get_entries(self, context):
        return self.entries


@six.add_metaclass(ExtensionHookPoint)
class ReviewRequestFieldSetsHook(ExtensionHook):
    """A hook for creating fieldsets on the side of the review request page.

    A fieldset contains one or more fields, and is mainly used to separate
    groups of fields from each other.

    This takes a list of fieldset classes as parameters, which it will
    later instantiate as necessary. Each fieldset can be pre-populated with
    one or more custom field classes.
    """
    def __init__(self, extension, fieldsets):
        super(ReviewRequestFieldSetsHook, self).__init__(extension)

        self.fieldsets = fieldsets

        for fieldset in fieldsets:
            register_review_request_fieldset(fieldset)

    def shutdown(self):
        for fieldset in self.fieldsets:
            unregister_review_request_fieldset(fieldset)


@six.add_metaclass(ExtensionHookPoint)
class ReviewRequestFieldsHook(ExtensionHook):
    """A hook for creating fields on the review request page.

    This is used to create custom fields on a review request page for
    requesting and storing data. A field can be editable, or it can be only
    for display purposes. See the classes in
    :py:mod:`reviewboard.reviews.fields` for more information and
    documentation.

    This hook takes the ID of a registered fieldset where the provided
    field classes should be added. Review Board supplies three built-in
    fieldset IDs:

        * ``main``      - The fieldset with Description and Testing Done.
        * ``info``      - The "Information" fieldset on the side.
        * ``reviewers`` - The "Reviewers" fieldset on the side.

    Any registered fieldset ID can be provided, whether from this extension
    or another.

    Field classes can only be added to a single fieldset.
    """
    def __init__(self, extension, fieldset_id, fields):
        super(ReviewRequestFieldsHook, self).__init__(extension)

        self.fieldset_id = fieldset_id
        self.fields = fields

        fieldset = get_review_request_fieldset(fieldset_id)

        for field_cls in fields:
            fieldset.add_field(field_cls)

    def shutdown(self):
        fieldset = get_review_request_fieldset(self.fieldset_id)

        for field_cls in self.fields:
            fieldset.remove_field(field_cls)


@six.add_metaclass(ExtensionHookPoint)
class CommentDetailDisplayHook(ExtensionHook):
    """This hook allows adding details to the display of comments.

    The hook can provide additional details to display for a comment in a
    review and e-mails.
    """
    def render_review_comment_detail(self, comment):
        raise NotImplementedError

    def render_email_comment_detail(self, comment, is_html):
        raise NotImplementedError


@six.add_metaclass(ExtensionHookPoint)
class ReviewUIHook(ExtensionHook):
    """This hook allows integration of Extension-defined Review UIs.

    This accepts a list of Review UIs specified by the Extension and
    registers them when the hook is created. Likewise, it unregisters
    the same list of Review UIs when the Extension is disabled.
    """
    def __init__(self, extension, review_uis):
        super(ReviewUIHook, self).__init__(extension)
        self.review_uis = review_uis

        for review_ui in self.review_uis:
            register_ui(review_ui)

    def shutdown(self):
        super(ReviewUIHook, self).shutdown()

        for review_ui in self.review_uis:
            unregister_ui(review_ui)


@six.add_metaclass(ExtensionHookPoint)
class FileAttachmentThumbnailHook(ExtensionHook):
    """This hook allows custom thumbnails to be defined for file attachments.

    This accepts a list of Mimetype Handlers specified by the Extension
    that must:

       *
          Subclass
          :py:class:`reviewboard.attachments.mimetypes.MimetypeHandler`
       *
          Define a list of file mimetypes it can handle in a class variable
          called `supported_mimetypes`
       *
          Define how to generate a thumbnail of that mimetype by overriding
          the instance function `def get_thumbnail(self):`

    These MimetypeHandlers are registered when the hook is created. Likewise,
    it unregisters the same list of MimetypeHandlers when the Extension is
    disabled.
    """
    def __init__(self, extension, mimetype_handlers):
        super(FileAttachmentThumbnailHook, self).__init__(extension)
        self.mimetype_handlers = mimetype_handlers

        for mimetype_handler in self.mimetype_handlers:
            register_mimetype_handler(mimetype_handler)

    def shutdown(self):
        super(FileAttachmentThumbnailHook, self).shutdown()

        for mimetype_handler in self.mimetype_handlers:
            unregister_mimetype_handler(mimetype_handler)


class ActionHook(ExtensionHook):
    """A hook for adding actions to a review request.

    Actions are displayed somewhere on the action bar (alongside Reviews,
    Close, etc.) of the review request. The subclasses of ActionHook should
    be used to determine placement.

    The provided actions parameter must be a list of actions. Each
    action must be a dict with the following keys:

       * `id`:           The ID of this action (optional).
       * `image`:        The path to the image used for the icon (optional).
       * `image_width`:  The width of the image (optional).
       * `image_height`: The height of the image (optional).
       * `label`:        The label for the action.
       * `url`:          The URI to invoke when the action is clicked.
                         If you want to invoke a javascript action, this should
                         be '#', and you should use a selector on the `id`
                         field to attach the handler (as opposed to a
                         javascript: URL, which doesn't work on all browsers).

    If your hook needs to access the template context, it can override
    get_actions and return results from there.
    """
    def __init__(self, extension, actions=[], *args, **kwargs):
        super(ActionHook, self).__init__(extension, *args, **kwargs)
        self.actions = actions

    def get_actions(self, context):
        """Returns the list of action information for this action."""
        return self.actions


@six.add_metaclass(ExtensionHookPoint)
class ReviewRequestActionHook(ActionHook):
    """A hook for adding an action to the review request page."""


@six.add_metaclass(ExtensionHookPoint)
class ReviewRequestDropdownActionHook(ActionHook):
    """A hook for adding an drop down action to the review request page.

    The actions for a drop down action should contain:

       * `id`:      The ID of this action (optional).
       * `label`:   The label of the drop-down.
       * `items`:   A list of ActionHook-style dicts (see ActionHook params).

    For example::

        actions = [{
            'id': 'id 0',
            'label': 'Title',
            'items': [
                {
                    'id': 'id 1',
                    'label': 'Item 1',
                    'url': '...',
                },
                {
                    'id': 'id 2',
                    'label': 'Item 2',
                    'url': '...',
                }
            ]
        }]
    """


@six.add_metaclass(ExtensionHookPoint)
class DiffViewerActionHook(ActionHook):
    """A hook for adding an action to the diff viewer page."""


@six.add_metaclass(ExtensionHookPoint)
class HeaderActionHook(ActionHook):
    """A hook for putting an action in the page header."""


@six.add_metaclass(ExtensionHookPoint)
class HeaderDropdownActionHook(ActionHook):
    """A hook for putting multiple actions into a header dropdown."""
