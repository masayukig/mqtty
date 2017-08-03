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

import collections
import errno
import logging
import math
import os
import re
import threading
import json
import time
import datetime

import dateutil.parser
import dateutil.tz
try:
    import ordereddict
except:
    pass
import requests
import requests.utils
import six
from six.moves import queue
from six.moves.urllib import parse as urlparse

import paho.mqtt.client as mqtt

import mqtty.version

HIGH_PRIORITY=0
NORMAL_PRIORITY=1
LOW_PRIORITY=2

TIMEOUT=30


class OfflineError(Exception):
    pass

class MultiQueue(object):
    def __init__(self, priorities):
        try:
            self.queues = collections.OrderedDict()
        except AttributeError:
            self.queues = ordereddict.OrderedDict()
        for key in priorities:
            self.queues[key] = collections.deque()
        self.condition = threading.Condition()
        self.incomplete = []

    def qsize(self):
        count = 0
        self.condition.acquire()
        try:
            for queue in self.queues.values():
                count += len(queue)
            return count + len(self.incomplete)
        finally:
            self.condition.release()

    def put(self, item, priority):
        added = False
        self.condition.acquire()
        try:
            if item not in self.queues[priority]:
                self.queues[priority].append(item)
                added = True
            self.condition.notify()
        finally:
            self.condition.release()
        return added

    def get(self):
        self.condition.acquire()
        try:
            while True:
                for queue in self.queues.values():
                    try:
                        ret = queue.popleft()
                        self.incomplete.append(ret)
                        return ret
                    except IndexError:
                        pass
                self.condition.wait()
        finally:
            self.condition.release()

    def find(self, klass, priority):
        results = []
        self.condition.acquire()
        try:
            for item in self.queues[priority]:
                if isinstance(item, klass):
                    results.append(item)
        finally:
            self.condition.release()
        return results

    def complete(self, item):
        self.condition.acquire()
        try:
            if item in self.incomplete:
                self.incomplete.remove(item)
        finally:
            self.condition.release()


class Sync(object):
    def __init__(self, app, disable_background_sync):
        self.user_agent = 'Mqtty/%s %s' % (mqtty.version.version_info.release_string(),
                                            requests.utils.default_user_agent())
        self.version = (0, 0, 0)
        self.offline = False
        self.account_id = None
        self.app = app
        self.log = logging.getLogger('mqtty.sync')
        self.queue = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY])
        self.result_queue = queue.Queue()
        self.session = requests.Session()
        # Create a websockets client
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        # Connect to the firehose
        FIREHOSE_HOST = 'firehose.openstack.org'
        self.log.debug("Connecting to " + FIREHOSE_HOST)
        self.client.connect(FIREHOSE_HOST)
        self.log.debug("Connected to " + FIREHOSE_HOST)

    def on_connect(self, client, userdata, flags, rc):
        self.log.debug("Connected with result code " + str(rc))
        # FIXME: just for draft implementation
        self.client.subscribe('#')

    def on_message(self, client, userdata, msg):
        # FIXME: just for draft implementation
        self.log.debug("on_message called =================")
        with self.app.db.getSession() as session:
            topic = session.getTopicByName(msg.topic)
            if not topic:
                topic = session.createTopic(msg.topic)
            session.createMessage(str(msg.payload), topic)
        # self.app.db.append(msg)
        self.log.debug(msg.topic + ": " + str(msg.payload))
        self.app.refresh()

    def run(self, pipe):
        task = None
        self.client.loop_forever()
        # while True:
        #     task = self._run(pipe, task)

    def _run(self, pipe, task=None):
        if not task:
            task = self.queue.get()
        self.log.debug('Run: %s' % (task,))
