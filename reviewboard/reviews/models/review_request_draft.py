from __future__ import unicode_literals

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from djblets.db.fields import ModificationTimestampField
from djblets.db.managers import ConcurrencyManager

from reviewboard.attachments.models import FileAttachment
from reviewboard.changedescs.models import ChangeDescription
from reviewboard.diffviewer.models import DiffSet
from reviewboard.reviews.models.group import Group
from reviewboard.reviews.models.base_review_request_details import \
    BaseReviewRequestDetails
from reviewboard.reviews.models.review_request import ReviewRequest
from reviewboard.reviews.models.screenshot import Screenshot
from reviewboard.reviews.fields import get_review_request_fields
from reviewboard.reviews.signals import review_request_published
from reviewboard.site.urlresolvers import local_site_reverse


class ReviewRequestDraft(BaseReviewRequestDetails):
    """A draft of a review request.

    When a review request is being modified, a special draft copy of it is
    created containing all the details of the review request. This copy can
    be modified and eventually saved or discarded. When saved, the new
    details are copied back over to the originating ReviewRequest.
    """
    review_request = models.ForeignKey(
        ReviewRequest,
        related_name="draft",
        verbose_name=_("review request"),
        unique=True)
    last_updated = ModificationTimestampField(
        _("last updated"))
    diffset = models.ForeignKey(
        DiffSet,
        verbose_name=_('diff set'),
        blank=True,
        null=True,
        related_name='review_request_draft')
    changedesc = models.ForeignKey(
        ChangeDescription,
        verbose_name=_('change description'),
        blank=True,
        null=True)
    target_groups = models.ManyToManyField(
        Group,
        related_name="drafts",
        verbose_name=_("target groups"),
        blank=True)
    target_people = models.ManyToManyField(
        User,
        verbose_name=_("target people"),
        related_name="directed_drafts",
        blank=True)
    screenshots = models.ManyToManyField(
        Screenshot,
        related_name="drafts",
        verbose_name=_("screenshots"),
        blank=True)
    inactive_screenshots = models.ManyToManyField(
        Screenshot,
        verbose_name=_("inactive screenshots"),
        related_name="inactive_drafts",
        blank=True)

    file_attachments = models.ManyToManyField(
        FileAttachment,
        related_name="drafts",
        verbose_name=_("file attachments"),
        blank=True)
    inactive_file_attachments = models.ManyToManyField(
        FileAttachment,
        verbose_name=_("inactive files"),
        related_name="inactive_drafts",
        blank=True)

    submitter = property(lambda self: self.review_request.submitter)
    repository = property(lambda self: self.review_request.repository)
    local_site = property(lambda self: self.review_request.local_site)

    depends_on = models.ManyToManyField('ReviewRequest',
                                        blank=True, null=True,
                                        verbose_name=_('Dependencies'),
                                        related_name='draft_blocks')

    # Set this up with a ConcurrencyManager to help prevent race conditions.
    objects = ConcurrencyManager()

    def get_latest_diffset(self):
        """Returns the diffset for this draft."""
        return self.diffset

    def is_accessible_by(self, user):
        """Returns whether or not the user can access this draft."""
        return self.is_mutable_by(user)

    def is_mutable_by(self, user):
        """Returns whether or not the user can modify this draft."""
        return self.review_request.is_mutable_by(user)

    @staticmethod
    def create(review_request):
        """Creates a draft based on a review request.

        This will copy over all the details of the review request that
        we care about. If a draft already exists for the review request,
        the draft will be returned.
        """
        draft, draft_is_new = \
            ReviewRequestDraft.objects.get_or_create(
                review_request=review_request,
                defaults={
                    'summary': review_request.summary,
                    'description': review_request.description,
                    'testing_done': review_request.testing_done,
                    'bugs_closed': review_request.bugs_closed,
                    'branch': review_request.branch,
                    'rich_text': review_request.rich_text,
                })

        if draft.changedesc is None and review_request.public:
            changedesc = ChangeDescription(rich_text=draft.rich_text)
            changedesc.save()
            draft.changedesc = changedesc

        if draft_is_new:
            for group in review_request.target_groups.all():
                draft.target_groups.add(group)

            for person in review_request.target_people.all():
                draft.target_people.add(person)

            for screenshot in review_request.screenshots.all():
                screenshot.draft_caption = screenshot.caption
                screenshot.save()
                draft.screenshots.add(screenshot)

            for screenshot in review_request.inactive_screenshots.all():
                screenshot.draft_caption = screenshot.caption
                screenshot.save()
                draft.inactive_screenshots.add(screenshot)

            for attachment in review_request.file_attachments.all():
                attachment.draft_caption = attachment.caption
                attachment.save()
                draft.file_attachments.add(attachment)

            for attachment in review_request.inactive_file_attachments.all():
                attachment.draft_caption = attachment.caption
                attachment.save()
                draft.inactive_file_attachments.add(attachment)

            for dependency in review_request.depends_on.all():
                draft.depends_on.add(dependency)

            draft.save()

        return draft

    def publish(self, review_request=None, user=None,
                send_notification=True):
        """Publishes this draft.

        This updates and returns the draft's ChangeDescription, which
        contains the changed fields. This is used by the e-mail template
        to tell people what's new and interesting.

        The draft's assocated ReviewRequest object will be used if one isn't
        passed in.

        The keys that may be saved in 'fields_changed' in the
        ChangeDescription are:

           *  'summary'
           *  'description'
           *  'testing_done'
           *  'bugs_closed'
           *  'depends_on'
           *  'branch'
           *  'target_groups'
           *  'target_people'
           *  'screenshots'
           *  'screenshot_captions'
           *  'diff'

        Each field in 'fields_changed' represents a changed field. This will
        save fields in the standard formats as defined by the
        'ChangeDescription' documentation, with the exception of the
        'screenshot_captions' and 'diff' fields.

        For the 'screenshot_captions' field, the value will be a dictionary
        of screenshot ID/dict pairs with the following fields:

           * 'old': The old value of the field
           * 'new': The new value of the field

        For the 'diff' field, there is only ever an 'added' field, containing
        the ID of the new diffset.

        The 'send_notification' parameter is intended for internal use only,
        and is there to prevent duplicate notifications when being called by
        ReviewRequest.publish.
        """
        if not review_request:
            review_request = self.review_request

        if not user:
            user = review_request.submitter

        if not self.changedesc and review_request.public:
            self.changedesc = ChangeDescription()

        def update_list(a, b, name, record_changes=True, name_field=None):
            aset = set([x.id for x in a.all()])
            bset = set([x.id for x in b.all()])

            if aset.symmetric_difference(bset):
                if record_changes and self.changedesc:
                    self.changedesc.record_field_change(name, a.all(), b.all(),
                                                        name_field)

                a.clear()
                for item in b.all():
                    a.add(item)

        for field_cls in get_review_request_fields():
            if field_cls.is_editable:
                field = field_cls(review_request)
                old_value = field.load_value(review_request)
                new_value = field.load_value(self)

                if field.has_value_changed(old_value, new_value):
                    field.save_value(new_value)

                    if self.changedesc:
                        field.record_change_entry(self.changedesc,
                                                  old_value, new_value)

        # Screenshots are a bit special.  The list of associated screenshots
        # can change, but so can captions within each screenshot.
        screenshots = self.screenshots.all()
        caption_changes = {}

        for s in review_request.screenshots.all():
            if s in screenshots and s.caption != s.draft_caption:
                caption_changes[s.id] = {
                    'old': (s.caption,),
                    'new': (s.draft_caption,),
                }

                s.caption = s.draft_caption
                s.save()

        # Now scan through again and set the caption correctly for newly-added
        # screenshots by copying the draft_caption over. We don't need to
        # include this in the changedescs here because it's a new screenshot,
        # and update_list will record the newly-added item.
        for s in screenshots:
            if s.caption != s.draft_caption:
                s.caption = s.draft_caption
                s.save()

        if caption_changes and self.changedesc:
            self.changedesc.fields_changed['screenshot_captions'] = \
                caption_changes

        update_list(review_request.screenshots, self.screenshots,
                    'screenshots', name_field="caption")

        # There's no change notification required for this field.
        review_request.inactive_screenshots.clear()
        for screenshot in self.inactive_screenshots.all():
            review_request.inactive_screenshots.add(screenshot)

        # Files are treated like screenshots. The list of files can
        # change, but so can captions within each file.
        files = self.file_attachments.all()
        caption_changes = {}

        for f in review_request.file_attachments.all():
            if f in files and f.caption != f.draft_caption:
                caption_changes[f.id] = {
                    'old': (f.caption,),
                    'new': (f.draft_caption,),
                }

                f.caption = f.draft_caption
                f.save()

        # Now scan through again and set the caption correctly for newly-added
        # files by copying the draft_caption over. We don't need to include
        # this in the changedescs here because it's a new screenshot, and
        # update_list will record the newly-added item.
        for f in files:
            if f.caption != f.draft_caption:
                f.caption = f.draft_caption
                f.save()

        if caption_changes and self.changedesc:
            self.changedesc.fields_changed['file_captions'] = \
                caption_changes

        update_list(review_request.file_attachments, self.file_attachments,
                    'files', name_field="display_name")

        # There's no change notification required for this field.
        review_request.inactive_file_attachments.clear()
        for attachment in self.inactive_file_attachments.all():
            review_request.inactive_file_attachments.add(attachment)

        if self.diffset:
            if self.changedesc:
                if review_request.local_site:
                    local_site_name = review_request.local_site.name
                else:
                    local_site_name = None

                url = local_site_reverse(
                    'view_diff_revision',
                    local_site_name=local_site_name,
                    args=[review_request.display_id, self.diffset.revision])
                self.changedesc.fields_changed['diff'] = {
                    'added': [(_("Diff r%s") % self.diffset.revision,
                               url,
                               self.diffset.id)],
                }

            self.diffset.history = review_request.diffset_history
            self.diffset.save()

        if self.changedesc:
            self.changedesc.timestamp = timezone.now()
            self.changedesc.rich_text = self.rich_text
            self.changedesc.public = True
            self.changedesc.save()
            review_request.changedescs.add(self.changedesc)

        review_request.rich_text = self.rich_text
        review_request.save()

        if send_notification:
            review_request_published.send(sender=review_request.__class__,
                                          user=user,
                                          review_request=review_request,
                                          changedesc=self.changedesc)

        return self.changedesc

    def get_review_request(self):
        """Returns the associated review request."""
        return self.review_request

    class Meta:
        app_label = 'reviews'
        ordering = ['-last_updated']
