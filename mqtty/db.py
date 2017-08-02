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
topic_table = Table(
    'topic', metadata,
    Column('key', Integer, primary_key=True),
    Column('name', String(255), index=True, unique=True, nullable=False),
    Column('subscribed', Boolean, index=True, default=False),
    Column('description', Text, nullable=False, default=''),
    Column('updated', DateTime, index=True),
)
message_table = Table(
    'message', metadata,
    Column('message_key', Integer, ForeignKey("message.key"), index=True),
    Column('message', Text, nullable=False),
)
topic_message_table = Table(
    'topic_message', metadata,
    Column('key', Integer, primary_key=True),
    Column('topic_key', Integer, ForeignKey("topic.key"), index=True),
    Column('message_key', Integer, ForeignKey("message.key"), index=True),
    Column('sequence', Integer, nullable=False),
    UniqueConstraint('message_key', 'sequence', name='message_key_sequence_const'),
    )


class Topic(object):
    def __init__(self, name, sequence):
        self.name = name
        self.sequence = sequence

    def addMessage(self, message):
        session = Session.object_session(self)
        seq = max([x.sequence for x in self.topic_messages] + [0])
        tm = TopicMessage(topic, self, seq+1)
        self.topic_messages.append(pt)
        self.messages.append(message)
        session.add(tm)
        session.flush()

    def removeMessage(self, message):
        session = Session.object_session(self)
        for tm in self.topic_messages:
            if tm.topic_key == topic.key:
                self.topic_messages.remove(tm)
                session.delete(tm)
        self.messages.remove(message)
        session.flush()

class TopicMessage(object):
    def __init__(self, project, topic, sequence):
        self.project_key = project.key
        self.topic_key = topic.key
        self.sequence = sequence


class Message(object):
    def __init__(self, message):
        self.message = message

    def addTopic(self, topic):
        session = Session.object_session(self)
        seq = max([x.sequence for x in self.topic_messages] + [0])
        tm = TopicMessage(topic, self, seq+1)
        self.topic_messages.append(tm)
        self.topics.append(project)
        session.add(tm)
        session.flush()

    def removeTopic(self, topic):
        session = Session.object_session(self)
        for tm in self.topic_messages:
            if tm.topic_key == topic.key:
                self.topic_messages.remove(tm)
                session.delete(tm)
        self.topics.remove(topic)
        session.flush()


mapper(Topic, topic_table, properties=dict(
    messages=relationship(Message,
                          order_by=topic_table.c.name,
                          viewonly=True),
))
mapper(Message, message_table, properties=dict(
    topics=relationship(Topic,
                        secondary=topic_message_table,
                        order_by=message_table.c.message,
                        viewonly=True),
    topic_messages=relationship(TopicMessage),
))
mapper(TopicMessage, topic_message_table)



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
