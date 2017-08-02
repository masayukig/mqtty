# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import re
import time
import logging
import threading

import alembic
import alembic.config
import six
import sqlalchemy
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Boolean, DateTime, Text, UniqueConstraint
from sqlalchemy.schema import ForeignKey
from sqlalchemy.orm import mapper, sessionmaker, relationship, scoped_session, joinedload
from sqlalchemy.orm.session import Session
from sqlalchemy.sql import exists
from sqlalchemy.sql.expression import and_

metadata = MetaData()

class Database(object):
    def __init__(self, app, dburi, search):
        self.log = logging.getLogger('mqtty.db')
        self.dburi = dburi
        self.search = search
        self.engine = create_engine(self.dburi)
        #metadata.create_all(self.engine)
        self.migrate(app)
        # If we want the objects returned from query() to be usable
        # outside of the session, we need to expunge them from the session,
        # and since the DatabaseSession always calls commit() on the session
        # when the context manager exits, we need to inform the session to
        # expire objects when it does so.
        self.session_factory = sessionmaker(bind=self.engine,
                                            expire_on_commit=False,
                                            autoflush=False)
        self.session = scoped_session(self.session_factory)
        self.lock = threading.Lock()
        self.topics = {}

    def getSession(self):
        return DatabaseSession(self)

    def migrate(self, app):
        conn = self.engine.connect()
        context = alembic.migration.MigrationContext.configure(conn)
        current_rev = context.get_current_revision()
        self.log.debug('Current migration revision: %s' % current_rev)

        has_table = self.engine.dialect.has_table(conn, "project")

        config = alembic.config.Config()
        config.set_main_option("script_location", "mqtty:alembic")
        config.set_main_option("sqlalchemy.url", self.dburi)
        config.mqtty_app = app

        if current_rev is None and has_table:
            self.log.debug('Stamping database as initial revision')
            alembic.command.stamp(config, "44402069e137")
        alembic.command.upgrade(config, 'head')

    def append(self, msg):
        self.topics.update({msg.topic: str(msg.payload)})


class DatabaseSession(object):
    def __init__(self, database):
        self.database = database
        self.session = database.session
        self.search = database.search

    def __enter__(self):
        self.database.lock.acquire()
        self.start = time.time()
        return self

    def __exit__(self, etype, value, tb):
        if etype:
            self.session().rollback()
        else:
            self.session().commit()
        self.session().close()
        self.session = None
        end = time.time()
        self.database.log.debug("Database lock held %s seconds" % (end-self.start,))
        self.database.lock.release()

    def abort(self):
        self.session().rollback()

    def commit(self):
        self.session().commit()

    def delete(self, obj):
        self.session().delete(obj)

    def vacuum(self):
        self.session().execute("VACUUM")
