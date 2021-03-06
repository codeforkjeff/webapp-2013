from urlparse import urljoin

from flask import Blueprint, render_template, flash, request, redirect, url_for, abort, send_file, jsonify, Response
from flask.ext.security import (
    login_required, roles_required, roles_accepted, current_user)

from flask_application.models import *
from flask_application.forms import ThingForm, AddThingToCollectionsForm, UploadForm, ThreadForm
from flask_application.helpers import archive_thing, compute_thing_file_path

from werkzeug.contrib.atom import AtomFeed

from ..permissions.thing import *
from ..permissions.talk import can_create_thread
from ..permissions.collection import can_add_thing_to_collections

app.jinja_env.globals['can_add_thing'] = can_add_thing
app.jinja_env.globals['can_edit_thing'] = can_edit_thing
app.jinja_env.globals['can_delete_thing'] = can_delete_thing
app.jinja_env.globals['can_add_file_to_thing'] = can_add_file_to_thing
app.jinja_env.globals['can_view_file_for_thing'] = can_view_file_for_thing
app.jinja_env.globals['can_create_thread'] = can_create_thread
app.jinja_env.globals[
    'can_add_thing_to_collections'] = can_add_thing_to_collections
app.jinja_env.globals[
    'can_delete_file_from_thing'] = can_delete_file_from_thing

thing = Blueprint('thing', __name__, url_prefix='/thing')


@thing.route('/')
@thing.route('/list')
@thing.route('/list/<int:page>')
def list(page=1):
    """
    See a list of all things
    """
    things = Thing.objects.order_by(
        '-modified_at', '-created_at').paginate(page=page, per_page=10)
    return render_template('thing/list.html',
                           title='All things',
                           things=things.items,
                           pagination=things,
                           endpoint='thing.list')


@thing.route('/request/list')
@thing.route('/request/list/<int:page>')
def list_requests(page=1):
    """
    See a list of all things
    """
    things = Thing.objects(files__size=0).order_by(
        '-created_at').paginate(page=page, per_page=10)
    return render_template('thing/list.html',
                           title='All requests',
                           things=things.items,
                           pagination=things,
                           endpoint='thing.list_requests')


@thing.route('/request/priority')
@thing.route('/request/priority/<int:page>')
def list_most_requested(page=1):
    """
    See a list of most requested things
    """
    things = Thing.objects(files__size=0).order_by(
        '-num_followers').paginate(page=page, per_page=10)
    return render_template('thing/list.html',
                           title='Most requested',
                           things=things.items,
                           pagination=things,
                           endpoint='thing.list_most_requested')


@thing.route('/list/no-requests')
@thing.route('/list/no-requests/<int:page>')
def list_nonrequests(page=1):
    """
    See a list of all things
    """
    things = Thing.objects(files__0__exists=True).order_by(
        '-modified_at', '-created_at').paginate(page=page, per_page=10)
    return render_template('thing/list.html',
                           title='All things (no requests)',
                           things=things.items,
                           pagination=things,
                           endpoint='thing.list_nonrequests')


@thing.route('/recent.atom')
def recent_feed():
    feed = AtomFeed('Recent', feed_url=request.url, url=request.url_root)
    things = Thing.objects.order_by('-modified_at', '-created_at').limit(25)
    for thing in things:
        feed.add(thing.title, unicode(thing.short_description),
                 content_type='html',
                 author=thing.format_makers_string(),
                 url=urljoin(request.url_root, url_for(
                     'thing.detail', id=thing.id)),
                 updated=thing.created_at,
                 published=thing.created_at)
    return feed.get_response()


@thing.route('/<id>', methods=['GET', 'POST'])
def detail(id):
    """
    See a thing in more detail
    """
    thing = Thing.objects.get_or_404(id=id)
    # xhr view
    if request.is_xhr:
        data = {
            'message' : 'Success',
            'data' : {
                'id' : str(thing.id),
                'title' : thing.title,
                'short_description' : thing.short_description,
                'description' : thing.description,
                'makers' : { str(m.maker.id): m.maker.name.full_name() for m in thing.makers }
            }    
        }
        if can_view_file_for_thing(thing):
            data['data']['files'] = []
            for f in thing.files:
                data['data']['files'].append(url_for('upload.serve_upload', filename=f.structured_file_name, _external=True))
        return jsonify(data)
    threads = Thread.objects.filter(origin=thing)
    # preview
    preview = thing.preview(filename="x200-0.jpg")
    if preview:
        preview = url_for('reference.preview', filename=preview)
    preview_url = url_for('reference.figleaf', md5=thing.preview(
        get_md5=True)) if preview else False
    # try new reader
    preview_url = '/static/reader.htm?0=%s-0' % thing.preview(get_md5=True) if preview_url else False
    # contributors
    contributors = [thing.creator]
    for f in thing.files:
        if not f.creator in contributors:
            contributors.append(f.creator)
    # Upload form
    uf = UploadForm()
    return render_template('thing/detail.html',
                           thing=thing,
                           metadata=thing.get_imported_data(),
                           contributors=contributors,
                           preview=preview,
                           preview_url=preview_url,
                           threads=threads,
                           upload_form=uf)


@thing.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    """
    Edit a thing
    """
    model = Thing.objects.get_or_404(id=id)
    if not can_edit_thing(model):
        abort(403)
    form = ThingForm(formdata=request.form, obj=model,
                     makers_raw=model.format_makers_string(), exclude=['creator'])
    if form.validate_on_submit():
        form.populate_obj(model)
        model.parse_makers_string(form.makers_raw.data)
        model.save()
        flash("Thing updated")
        return redirect(url_for("thing.detail", id=model.id))
    return render_template('thing/edit.html',
                           title='Edit',
                           form=form)


@thing.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """
    Add a new thing
    """
    if current_user.has_role('spammer'):
        abort(403)
    m = request.args.get('maker', '')
    c = request.args.get('collection', None)
    form = ThingForm(formdata=request.form, makers_raw=m,
                     collection=c, exclude=['creator'])
    if form.validate_on_submit():
        thing = Thing()
        form.populate_obj(thing)
        thing.parse_makers_string(form.makers_raw.data)
        thing.save()
        # If there are already files to upload do it here
        files = request.files
        for key, file in files.iteritems():
            um = UploadManager()
            u = um.set_uploaded_file(file)
            if thing:
                thing.add_file(u)
        #
        if form.collection.data:
            collection = Collection.objects(id=form.collection.data).first()
            if collection:
                collection.add_thing(thing=thing)
        flash("'%s' created! Now, upload a file. When you are done <a href='%s'>click here</a>. If you skip this step, then this will be classified as a 'request' and hopefully someone else will upload a file." %
              (thing.title, url_for('thing.detail', id=thing.id)))
        # Upload form
        upload_form = UploadForm()
    else:
        thing = False
        upload_form = False
    return render_template('thing/add.html',
                           title='Add Thing',
                           form=form,
                           upload_form=upload_form,
                           thing=thing
                           )


@thing.route('/<id>/delete', methods=['GET', 'POST'])
@roles_accepted('admin', 'editor')
def delete(id):
    """
    Delete a thing (untested)
    """
    model = Thing.objects.get_or_404(id=id)
    if not can_delete_thing(model):
        abort(403)
    model.delete()
    flash("Thing deleted")
    return redirect(url_for("thing.list"))


@thing.route('/<id>/remove/<upload_id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'editor')
def remove_file(id, upload_id):
    thing = Thing.objects.get_or_404(id=id)
    upload = Upload.objects.get_or_404(id=upload_id)
    if not can_delete_file_from_thing(thing):
        abort(403)
    thing.remove_file(upload)
    flash("File removed")
    return redirect(url_for("thing.detail", id=id))


@thing.route('/actions/for/<id>')
def sort_actions(id):
    hide = request.args.get('hide', '')
    model = Thing.objects.get_or_404(id=id)
    if not hide == 'collections':
        form = AddThingToCollectionsForm()
        form.set_thing(model)
    else:
        form = None
    queues = Queue.objects.filter(creator=current_user.get_id())
    return render_template(
        'thing/sort_actions.html',
        form=form,
        queues=queues,
        thing=model
    )


@thing.route('/<id>.opf', methods=['GET', 'POST'])
def opf(id):
    """
    Get opf metadata for a thing
    """
    thing = Thing.objects.get_or_404(id=id)
    try:
        metadata = Metadata.objects.get(thing=thing)
    except:
        metadata = Metadata(thing=thing)
    return Response(metadata.opf,
                    mimetype="application/oebps-package+xml",
                    headers={"Content-Disposition": "attachment;filename=%s.opf" % thing.id})


@thing.route('/<id>/calibre')
def calibre(id):
    """
    Export a zip of metadata and cover
    """
    thing = Thing.objects.get_or_404(id=id)
    archive = archive_thing(thing)
    return Response(archive,
                    mimetype="application/x-zip-compressed",
                    headers={"Content-Disposition": "attachment;filename=%s.zip" % thing.id})


@thing.route('/<id>/calibre/status')
def calibre_status(id):
    """
    Export a zip of metadata and cover
    """
    thing = Thing.objects.get_or_404(id=id)
    try:
        metadata = Metadata.objects.get(thing=thing)
    except:
        metadata = Metadata(thing=thing)
        metadata.reload()

    return jsonify({
        'message': 'Success',
        'data': {
            'id': id,
            'version': metadata.version
        },
        'request': {
            'id': id
        }
    })


@thing.route('/<id>/calibre/commit', methods=['POST'])
def calibre_commit(id):
    """
    Ingests
    """
    from flask_application.helpers import opf2id, opf_date
    thing = Thing.objects.get_or_404(id=id)
    # first try and save the cover
    cover = request.files['cover'] if 'cover' in request.files else None
    cover_ext = request.form[
        'cover_ext'] if 'cover_ext' in request.form else None  # not used for now
    if cover:
        cover.save(compute_thing_file_path(thing, 'cover.jpg', makedirs=True))

    # now try metadata
    opf = request.form['opf'] if 'opf' in request.form else None
    if not opf:
        return {'message': 'No opf was posted', 'data': {}, 'request': {}}
    try:
        metadata = Metadata.objects.get(thing=thing)
    except:
        metadata = Metadata(thing=thing)
        metadata.reload()

    success = metadata.set_opf(opf)
    if success:
        retval = {'message': '%s successfully updated' % thing.title,
                  'data': {}, 'request': {'opf': opf}}
    else:
        retval = {'message': '%s failed. A newer version seems to exist already.' % thing.title,
                  'data': {}, 'request': {'opf': opf}}
    return jsonify(retval)


@thing.route('/calibre/add', methods=['POST'])
def calibre_add():
    """
    Creates a new Thing, via a different interface
    """
    z = request.files['zip'] if 'zip' in request.files else None
    if not z:
        return {'message': 'Failed', 'data': {}, 'request': {}}
    print z
    return {}

    # now try metadata
    opf = request.form['opf'] if 'opf' in request.form else None
    if not opf:
        return {'message': 'No opf was posted', 'data': {}, 'request': {}}
    try:
        metadata = Metadata.objects.get(thing=thing)
    except:
        metadata = Metadata(thing=thing)
        metadata.reload()

    success = metadata.set_opf(opf)
    if success:
        retval = {'message': '%s successfully updated' % thing.title,
                  'data': {}, 'request': {'opf': opf}}
    else:
        retval = {'message': '%s failed. A newer version seems to exist already.' % thing.title,
                  'data': {}, 'request': {'opf': opf}}
    return jsonify(retval)
