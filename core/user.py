from __future__ import unicode_literals

from mongoengine import StringField, DictField, BooleanField
from flask_mongoengine.wtf import model_form

from core.database import YetiDocument


class User(YetiDocument):
    available_settings = dict()

    login = StringField(required=True, unique=True)
    enabled = BooleanField(required=True, default=True)
    settings = DictField()

    def is_authenticated(self):
        print repr(self.enabled), self.enabled == True
        return self.enabled

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return unicode(self.id)

    def has_settings(self, settings):
        for setting in settings:
            if setting not in self.settings:
                return False
        return True

    @classmethod
    def get_form(klass):
        return model_form(User)

    @classmethod
    def register_setting(klass, id, name, description):
        klass.available_settings[id] = {
            'name': name,
            'description': description
        }

    # This is only used because user management / access control is not yet implemented
    @staticmethod
    def get_default_user():
        return User.objects(login='yeti').modify(upsert=True, new=True, login='yeti')
