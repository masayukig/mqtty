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
import getpass
import os
import re
try:
    import ordereddict
except:
    pass
import yaml

from six.moves.urllib import parse as urlparse
import voluptuous as v

import mqtty.palette
import mqtty.keymap

try:
    OrderedDict = collections.OrderedDict
except AttributeError:
    OrderedDict = ordereddict.OrderedDict

DEFAULT_CONFIG_PATH='~/.mqtty.yaml'

class ConfigSchema(object):
    server = {v.Required('name'): str,
              v.Required('host'): str,
              }
    servers = [server]

    topic = {'name': str,
              'topic': str,
              }
    subscribed_topics = [topic]

    _sort_by = v.Any('number', 'updated', 'last-seen', 'project')
    sort_by = v.Any(_sort_by, [_sort_by])

    text_replacement = {'text': v.Any(str,
                                      {'color': str,
                                       v.Required('text'): str})}

    link_replacement = {'link': {v.Required('url'): str,
                                 v.Required('text'): str}}

    search_replacement = {'search': {v.Required('query'): str,
                                     v.Required('text'): str}}

    replacement = v.Any(text_replacement, link_replacement, search_replacement)

    palette = {v.Required('name'): str,
               v.Match('(?!name)'): [str]}

    palettes = [palette]


    dashboard = {v.Required('name'): str,
                 v.Required('query'): str,
                 v.Optional('sort-by'): sort_by,
                 v.Optional('reverse'): bool,
                 v.Required('key'): str}

    dashboards = [dashboard]

    reviewkey_approval = {v.Required('category'): str,
                          v.Required('value'): int}

    reviewkey = {v.Required('approvals'): [reviewkey_approval],
                 'submit': bool,
                 v.Required('key'): str}

    reviewkeys = [reviewkey]

    hide_comment = {v.Required('author'): str}

    hide_comments = [hide_comment]

    change_list_options = {'sort-by': sort_by,
                           'reverse': bool}

    keymap = {v.Required('name'): str,
              v.Match('(?!name)'): v.Any([[str], str], [str], str)}

    keymaps = [keymap]

    thresholds = [int, int, int, int, int, int, int, int]
    size_column = {v.Required('type'): v.Any('graph', 'splitGraph', 'number',
                                             'disabled', None),
                   v.Optional('thresholds'): thresholds}

    def getSchema(self, data):
        schema = v.Schema({v.Required('servers'): self.servers,
                           'subscribed-topics': self.subscribed_topics,
                           'palettes': self.palettes,
                           'palette': str,
                           'keymaps': self.keymaps,
                           'keymap': str,
                           'dashboards': self.dashboards,
                           'reviewkeys': self.reviewkeys,
                           'change-list-query': str,
                           'diff-view': str,
                           'hide-comments': self.hide_comments,
                           'thread-changes': bool,
                           'display-times-in-utc': bool,
                           'handle-mouse': bool,
                           'breadcrumbs': bool,
                           'change-list-options': self.change_list_options,
                           'expire-age': str,
                           'size-column': self.size_column,
                           })
        return schema

class Config(object):
    def __init__(self, server=None, palette='default', keymap='default',
                 path=DEFAULT_CONFIG_PATH):
        self.path = os.path.expanduser(path)

        if not os.path.exists(self.path):
            self.printSample()
            exit(1)

        self.config = yaml.load(open(self.path))
        schema = ConfigSchema().getSchema(self.config)
        schema(self.config)
        server = self.getServer(server)
        self.server = server

        self.subscribed_topic = self.get_topic('default')

        self.dburi = server.get('dburi',
                                'sqlite:///' + os.path.expanduser('~/.mqtty.db'))
        socket_path = server.get('socket', '~/.mqtty.sock')
        self.socket_path = os.path.expanduser(socket_path)
        log_file = server.get('log-file', '~/.mqtty.log')
        self.log_file = os.path.expanduser(log_file)
        lock_file = server.get('lock-file', '~/.mqtty.%s.lock' % server['name'])
        self.lock_file = os.path.expanduser(lock_file)

        self.palettes = {'default': mqtty.palette.Palette({}),
                         'light': mqtty.palette.Palette(mqtty.palette.LIGHT_PALETTE),
                         }
        for p in self.config.get('palettes', []):
            if p['name'] not in self.palettes:
                self.palettes[p['name']] = mqtty.palette.Palette(p)
            else:
                self.palettes[p['name']].update(p)
        self.palette = self.palettes[self.config.get('palette', palette)]

        self.keymaps = {'default': mqtty.keymap.KeyMap({}),
                        'vi': mqtty.keymap.KeyMap(mqtty.keymap.VI_KEYMAP)}
        for p in self.config.get('keymaps', []):
            if p['name'] not in self.keymaps:
                self.keymaps[p['name']] = mqtty.keymap.KeyMap(p)
            else:
                self.keymaps[p['name']].update(p)
        self.keymap = self.keymaps[self.config.get('keymap', keymap)]


        self.project_change_list_query = self.config.get('change-list-query', 'status:open')

        self.diff_view = self.config.get('diff-view', 'side-by-side')

        self.dashboards = OrderedDict()
        for d in self.config.get('dashboards', []):
            self.dashboards[d['key']] = d
            self.dashboards[d['key']]

        self.reviewkeys = OrderedDict()
        for k in self.config.get('reviewkeys', []):
            self.reviewkeys[k['key']] = k

        self.hide_comments = []
        for h in self.config.get('hide-comments', []):
            self.hide_comments.append(re.compile(h['author']))

        self.thread_changes = self.config.get('thread-changes', True)
        self.utc = self.config.get('display-times-in-utc', False)
        self.breadcrumbs = self.config.get('breadcrumbs', True)
        self.handle_mouse = self.config.get('handle-mouse', True)

        change_list_options = self.config.get('change-list-options', {})
        self.change_list_options = {
            'sort-by': change_list_options.get('sort-by', 'number'),
            'reverse': change_list_options.get('reverse', False)}

        self.expire_age = self.config.get('expire-age', '2 months')

        self.size_column = self.config.get('size-column', {})
        self.size_column['type'] = self.size_column.get('type', 'graph')
        if self.size_column['type'] == 'graph':
            self.size_column['thresholds'] = self.size_column.get('thresholds',
                [1, 10, 100, 1000])
        else:
            self.size_column['thresholds'] = self.size_column.get('thresholds',
                [1, 10, 100, 200, 400, 600, 800, 1000])

    def getServer(self, name=None):
        for server in self.config['servers']:
            if name is None or name == server['name']:
                return server
        return None

    def get_topic(self, name=None):
        for topic in self.config['subscribed-topics']:
            if name is None or name == topic['name']:
                return topic
        return None

    def printSample(self):
        filename = 'share/mqtty/examples'
        print("""Mqtty requires a configuration file at ~/.mqtty.yaml
If the file contains a password then permissions must be set to 0600.

Several sample configuration files were installed with Mqtty and are
available in %s in the root of the installation.

For more information, please see the README.
""" % (filename,))
