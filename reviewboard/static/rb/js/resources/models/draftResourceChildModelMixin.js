/*
 * Mixin for resources that are children of a draft resource.
 *
 * This will ensure that the draft is in a proper state before operating
 * on the resource.
 */
RB.DraftResourceChildModelMixin = {
    /*
     * Calls a function when the object is ready to use.
     *
     * This will ensure the draft is created before ensuring the object
     * is ready.
     */
    ready: function(options, context) {
        this.get('parentObject').ensureCreated({
            success: _.bind(_.super(this).ready, this, options, context),
            error: options.error
        }, context);
    }
};
