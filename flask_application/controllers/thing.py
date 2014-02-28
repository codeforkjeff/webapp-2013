from urlparse import urljoin

from flask import Blueprint, render_template, flash, request, redirect, url_for, abort
from flask.ext.security import (login_required, roles_required, roles_accepted, current_user)

from flask_application.models import *
from flask_application.forms import ThingForm, AddThingToCollectionsForm, UploadForm, ThreadForm

from werkzeug.contrib.atom import AtomFeed

from ..permissions.thing import *
from ..permissions.talk import can_create_thread
from ..permissions.collection import can_add_thing_to_collections

app.jinja_env.globals['can_add_thing'] = can_add_thing
app.jinja_env.globals['can_edit_thing'] = can_edit_thing
app.jinja_env.globals['can_add_file_to_thing'] = can_add_file_to_thing
app.jinja_env.globals['can_view_file_for_thing'] = can_view_file_for_thing
app.jinja_env.globals['can_create_thread'] = can_create_thread
app.jinja_env.globals['can_add_thing_to_collections'] = can_add_thing_to_collections

thing = Blueprint('thing', __name__, url_prefix='/thing')



@thing.route('/')
@thing.route('/list')
@thing.route('/list/<int:page>')
def list(page=1):
	"""
	See a list of all things
	"""
	things = Thing.objects.order_by('-modified_at', '-created_at').paginate(page=page, per_page=10)
	return render_template('thing/list.html',
		title = 'All things',
		things = things.items,
		pagination = things)


@thing.route('/')
@thing.route('/request/list')
@thing.route('/request/list/<int:page>')
def list_requests(page=1):
	"""
	See a list of all things
	"""
	things = Thing.objects(files__size=0).order_by('-created_at').paginate(page=page, per_page=10)
	return render_template('thing/list.html',
		title = 'All requests',
		things = things.items,
		pagination = things)


@thing.route('/')
@thing.route('/list/no-requests')
@thing.route('/list/no-requests/<int:page>')
def list_nonrequests(page=1):
	"""
	See a list of all things
	"""
	things = Thing.objects(files__0__exists=True).order_by('-modified_at', '-created_at').paginate(page=page, per_page=10)
	return render_template('thing/list.html',
		title = 'All things (no requests)',
		things = things.items,
		pagination = things)

@thing.route('/recent.atom')
def recent_feed():
	feed = AtomFeed('Recent', feed_url=request.url, url=request.url_root)
	things = Thing.objects.order_by('-modified_at', '-created_at').limit(25)
	for thing in things:
		feed.add(thing.title, unicode(thing.short_description),
			content_type='html',
			author=thing.format_makers_string(),
			url=urljoin(request.url_root, url_for('thing.detail', id=thing.id)),
			updated=thing.created_at,
			published=thing.created_at)
	return feed.get_response()


@thing.route('/<id>', methods= ['GET', 'POST'])
def detail(id):
	"""
	See a thing in more detail
	"""
	thing = Thing.objects.get_or_404(id=id)
	collections = Collection.objects.filter(things__thing=thing)
	threads = Thread.objects.filter(origin=thing)
	# Upload form
	uf = UploadForm()
	# Add this thing to one or more collections
	cf = AddThingToCollectionsForm(formdata=request.form)
	cf.set_thing(thing)
	if cf.validate_on_submit():
		ct = CollectedThing()
		cf.populate_obj(ct)
		cf.collection.data.add_thing(ct)
		flash("Thing added to Collection")
		return redirect(url_for("thing.detail", id=thing.id))
	return render_template('thing/detail.html',
		thing = thing,
		collections = collections,
		collection_form = cf,
		threads = threads,
		upload_form = uf)


@thing.route('/<id>/edit', methods= ['GET', 'POST'])
def edit(id):
	"""
	Edit a thing
	"""
	model = Thing.objects.get_or_404(id=id)
	if not can_edit_thing(model):
		abort(403)
	form = ThingForm(formdata=request.form, obj=model, makers_raw=model.format_makers_string(), exclude=['creator'])
	if form.validate_on_submit():
		form.populate_obj(model)
		model.parse_makers_string(form.makers_raw.data)
		model.save() 
		flash("Thing updated")
		return redirect(url_for("thing.detail", id=model.id))
	return render_template('thing/edit.html',
		title = 'Edit',
		form = form)


@thing.route('/add', methods= ['GET', 'POST'])
@login_required
def add():
	"""
	Add a new thing
	"""
	m = request.args.get('maker', '')
	c = request.args.get('collection', None)
	form = ThingForm(formdata=request.form, makers_raw=m, collection=c, exclude=['creator'])
	if form.validate_on_submit():
		thing = Thing()
		form.populate_obj(thing)
		thing.parse_makers_string(form.makers_raw.data)
		thing.save()
		if form.collection.data:
			collection = Collection.objects(id=form.collection.data).first()
			if collection:
				collection.add_thing(thing)
		flash("'%s' created! Now, upload a file. When you are done <a href='%s'>click here</a>. If you skip this step, then this will be classified as a 'request' and hopefully someone else will upload a file." % (thing.title, url_for('thing.detail', id=thing.id)))
		# Upload form
		upload_form = UploadForm()
	else:
		thing = False
		upload_form = False
	return render_template('thing/add.html',
		title = 'Add Thing',
		form=form,
		upload_form=upload_form,
		thing=thing
  )


@thing.route('/<id>', methods= ['DELETE'])
@roles_accepted('admin', 'editor', 'contributor')
def delete():
	"""
	Delete a thing (untested)
	"""
	model = Thing.objects.get_or_404(id=id)
	if not can_delete_thing(model):
		abort(403)
	model.delete()
	flash("Thing deleted")
	return redirect(url_for("thing.list"))
	

@thing.route('/actions/for/<id>')
def sort_actions(id):
	hide = request.args.get('hide', '')
	model = Thing.objects.get_or_404(id=id)
	if not hide=='collections':
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