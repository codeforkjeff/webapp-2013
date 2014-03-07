import re, datetime

from flask import url_for
from flask.ext.security import current_user 

from . import db, CreatorMixin, FollowersMixin, SolrMixin
from .user import User
from .maker import Maker, Name
from .upload import Upload


class MakerWithRole(db.EmbeddedDocument):
    """
    In the context of a Thing, a Maker might have a special role (ie. "editor")
    This class allows us to store the Maker with the role
    """
    maker = db.ReferenceField(Maker)
    role = db.StringField(max_length=32)


class Thing(SolrMixin, CreatorMixin, FollowersMixin, db.Document):
    """
    Thing model
    """
    meta = {
        'ordering': ['title'],
        'indexes': ['creator','makers']
    }

    title = db.StringField(max_length=255)
    makers = db.ListField(db.EmbeddedDocumentField(MakerWithRole))
    makers_sorted = db.StringField()
    short_description = db.StringField(max_length=512)
    description = db.StringField()
    modified_at = db.DateTimeField()
    files = db.ListField(db.ReferenceField(Upload))

    is_request = True

    def __init__(self, *args, **kwargs):
        super(Thing, self).__init__(*args, **kwargs)
        if self.modified_at is None:
             self.modified_at = self.created_at
        self._update_request_status()

    def _update_request_status(self):
        self.is_request = False if len(self.files)>0 else True

    def add_file(self, f, calibre_move=True):
        self.update(add_to_set__files=f)
        self.update(set__modified_at=datetime.datetime.now)
        self._update_request_status()
        # This may not be for everyone... make it an option?
        if calibre_move:
            f.apply_calibre_folder_structure(self.get_maker_and_title())
        self.tell_followers(self.title, '''
            A new file has been added to <a href="%s">%s</a>
            ''' % (url_for('thing.detail', id=self.id, _external=True), self.title))

    def remove_file(self, f):
        self.update(pull__files=f)
        self._update_request_status()

    def format_makers_string(self):
        names = []
        for m in self.makers:
            names.append(m.maker.format_name(m.role))
        return ', '.join(names)

    def update_makers_sorted(self):
        names = []
        for m in self.makers:
            names.append(m.maker.sort_by)
        self.makers_sorted = '| '.join(names)

    def parse_makers_string(self, raw):
        """
        If the makers are provided as a raw string, then the Maker class provides 
        a way for the name string to be parsed into a structure. 
        Roles might be specified in parentheses after the name:
        Saul Bellow, J. M. Coetzee (Introduction)
        """
        makers_before = self.makers
        self.makers = []
        raw_names = raw.split(',')
        for s in raw_names:
            raw_name = str(s).strip()
            pattern = r'(.*)\s?\((.*)\)$'
            match = re.search(pattern, raw_name)
            if match is None:
                n = raw_name
                role = ""
            else:
                (n, role) = match.group(1,2)
            name = Name()
            name.parse(n)
            m = Maker.objects(name=name)
            if m.count() > 0:
                maker = m.first()
            else:
                maker = Maker()
                maker.init_with_name(name)
                maker.save()
            self.makers.append(MakerWithRole(maker=maker, role=role))
        self.update_makers_sorted()
        # @todo tell_followers() - also refactor this code

    def format_for_filename(self):
        for m in self.makers:
            return "%s %s" % (m.maker.sort_by, self.title)
        # otherwise...
        return self.title


    def get_maker_and_title(self):
        for m in self.makers:
            return (m.maker.display_name, self.title)
        # otherwise...
        return ('', self.title)

    def save(self, *args, **kwargs):
        super(Thing, self).save(*args, **kwargs)
        for f in self.files:
            f.apply_calibre_folder_structure(self.get_maker_and_title())

    def build_solr(self):
        from .collection import Collection
        return {
            '_id' : self.id,
            'content_type' : 'thing',
            'title': self.title,
            'short_description': self.short_description,
            'description': self.description,
            'makers': [m.maker.id for m in self.makers],
            'makers_string': self.format_makers_string(),
            'makers_sorted': self.makers_sorted,
            'collections' : [c.id for c in Collection.objects.filter(things__thing=self)]
        }