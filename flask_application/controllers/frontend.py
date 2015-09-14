#!/usr/bin/env python

import datetime

from flask import Blueprint, request, redirect, url_for, render_template, get_template_attribute, abort, jsonify, send_from_directory
from flask_application import app
from flask.ext.security import login_required, current_user

from ..models import *

frontend = Blueprint('frontend', __name__)

@frontend.route('/')
def index():
	recent_collections = Collection.objects(accessibility__ne='private').limit(3).order_by('-things.created_at')
	recent_comments = Thread.objects(origin__exists=False).exclude('comments').order_by('-priority','-last_comment').limit(3)
	recent_things = Thing.objects(files__0__exists=True).order_by('-modified_at', '-created_at').paginate(page=1, per_page=10)
	return render_template('frontend/home.html',
		title = app.config['SITE_NAME'],
		things = recent_things.items,
		collections = recent_collections,
		comments = recent_comments,
		pagination = recent_things,
		endpoint = 'thing.list_nonrequests')


@frontend.route('/robots.txt')
@frontend.route('/sitemap.xml')
def static_from_root():
	return send_from_directory(app.static_folder, request.path[1:])


@frontend.route('/follow/<type>/<id>')
def follow(type, id):
	"""
	Adds current user to followers
	Returns JSON
	"""
	if type=='collection':
		model = Collection.objects.get_or_404(id=id)
	elif type=='queue':
		model = Queue.objects.get_or_404(id=id)
	elif type=='maker':
		model = Maker.objects.get_or_404(id=id)
	elif type=='thread':
		model = Thread.objects.get_or_404(id=id)
	elif type=='thing':
		model = Thing.objects.get_or_404(id=id)
	else:
		abort(404)

	user = User.objects(id=current_user.get_id()).first()	
	model.add_follower(user)
	if type=='collection':
		cached = Cache.objects(name="collections-for-%s" % current_user.get_id()).first()
		if cached:
			cached.delete()
	return jsonify({
		'result': 'success',
		'message': get_template_attribute('frontend/macros.html', 'unfollow')(model)
	})


@frontend.route('/unfollow/<type>/<id>')
def unfollow(type, id):
	"""
	Removes current user as follower
	Returns JSON
	"""
	if type=='collection':
		model = Collection.objects.get_or_404(id=id)
	elif type=='queue':
		model = Queue.objects.get_or_404(id=id)
	elif type=='maker':
		model = Maker.objects.get_or_404(id=id)
	elif type=='thread':
		model = Thread.objects.get_or_404(id=id)
	elif type=='thing':
		model = Thing.objects.get_or_404(id=id)
	else:
		abort(404)

	user = User.objects(id=current_user.get_id()).first()
	model.remove_follower(user)
	if type=='collection':
		cached = Cache.objects(name="collections-for-%s" % current_user.get_id()).first()
		if cached:
			cached.delete()
	return jsonify({
		'result': 'success',
		'message': get_template_attribute('frontend/macros.html', 'follow')(model)
	})	


@frontend.route('/search')
@frontend.route('/search/<type>')
def search(type=False):
	is_ajax = request.args.get('ajax', None)
	query = request.args.get('query', "")
	page = int(request.args.get('page', "1"))
	if not type:
		return render_template(
			'frontend/search.html',
			query = query,
			title = 'Search for'
		)
	if is_ajax and query=="":
		return 'I am not searching for anything'
	num = 10
	start = (page-1)*num
	if type=='things':
		results = elastic.search('thing', 'title:"%s" 	%s'%(query,query))
		content = get_template_attribute('frontend/macros.html', 'search_results')(results, 'thing.detail')			
	elif type=='makers':
		results = elastic.search('maker', 'title:"%s" 	%s'%(query,query))
		content = get_template_attribute('frontend/macros.html', 'search_results')(results, 'maker.detail')
	elif type=='discussions':
		results = elastic.search('discussion', 'title:"%s" 	%s'%(query,query))
		content = get_template_attribute('frontend/macros.html', 'search_results')(results, 'talk.thread')
	elif type=='collections':
		results = elastic.search('collection', 'title:"%s" 	%s'%(query,query))
		content = get_template_attribute('frontend/macros.html', 'search_results')(results, 'collection.detail')
	if is_ajax:
		return content
	else: 
		return render_template(
		'frontend/search_results.html',
		query = query,
		title = 'Search for',
		content = content,
		page_next = page + 1,
		type = type
	)

@frontend.route('/research')
@frontend.route('/research/<filter_type>/<filter_id>')
def research(filter_type=None, filter_id=None):
	""" Full text search results """
	query = request.args.get('query', "")
	mlt = request.args.get('mlt', "")
	page = int(request.args.get('page', "1"))
	num = 10
	start = (page-1)*num
	content = ""
	ready = False

	if not mlt=="":
		ready = True
	elif not query=="":
		ready = True

	if ready:
		if filter_type and filter_id:
			results = elastic.search('page', 
				query={'searchable_text': query}, 
				filter={filter_type:filter_id},
				highlight='searchable_text',
				fields=['page','md5','thing'])
		else:
			results = elastic.search('page', 
				query={'searchable_text': query}, 
				highlight='searchable_text',
				fields=['page','md5','thing'])
		# Build list of results 
		things = []
		for comp_id, result, highlight in results:
			# id[0] is the upload id, id[1] is upload page
			id = comp_id.split('_')
			if len(id)==2:
				u = Upload.objects.get(id=id[0])
				if u:
					try:
						t = Thing.objects.get(id=result['thing'][0])
						things.append((t, result['md5'][0], result['page'][0], id, highlight ))
					except:
						pass
		print things
		content = get_template_attribute('frontend/macros.html', 'fulltext_search_results')(things, query)
	
	return render_template(
		'frontend/search_fulltext.html',
		query = query,
		title = 'Search for',
		content = content,
		page_next = page + 1,
		type = type
	)


@frontend.route('/deepsearch')
def deepsearch():
	""" Search full text by author title and some phrase """
	phrase = request.args.get('phrase', "")
	author = request.args.get('author', "")
	title = request.args.get('title', "")
	
	new_query = "%s" % phrase
	#the_query = solr.query(searchable_text=new_query).filter(content_type="page").sort_by("-score")
	#the_query = solr.query(title='plague').filter(content_type="thing").sort_by("-score")
	#the_query = solr.query(_id='54352bfdc738464b67c2d29c_*').filter(content_type="page").sort_by("-score")
	#the_query = solr.query(title='plague',makers_string='ahmad').filter(content_type="thing").sort_by("-score")
	results = the_query.execute()
	# Build list of results 
	things = []
	for result in results:
		print result
	return "hello"
