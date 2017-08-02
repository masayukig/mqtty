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

import logging
import urwid

import paho.mqtt.client as mqtt

from mqtty import keymap
from mqtty import mywid
from mqtty.view import mouse_scroll_decorator


@mouse_scroll_decorator.ScrollByWheel
class TopicListView(urwid.WidgetWrap, mywid.Searchable):
    title = "Topics"
    def getCommands(self):
        return [
            (keymap.TOGGLE_LIST_SUBSCRIBED,
             "Toggle whether only subscribed projects or all projects are listed"),
            (keymap.TOGGLE_LIST_REVIEWED,
             "Toggle listing of projects with unreviewed changes"),
            (keymap.TOGGLE_SUBSCRIBED,
             "Toggle the subscription flag for the selected project"),
            (keymap.REFRESH,
             "Sync subscribed projects"),
            (keymap.TOGGLE_MARK,
             "Toggle the process mark for the selected project"),
            (keymap.NEW_PROJECT_TOPIC,
             "Create project topic"),
            (keymap.DELETE_PROJECT_TOPIC,
             "Delete selected project topic"),
            (keymap.MOVE_PROJECT_TOPIC,
             "Move selected project to topic"),
            (keymap.COPY_PROJECT_TOPIC,
             "Copy selected project to topic"),
            (keymap.REMOVE_PROJECT_TOPIC,
             "Remove selected project from topic"),
            (keymap.RENAME_PROJECT_TOPIC,
             "Rename selected project topic"),
            (keymap.INTERACTIVE_SEARCH,
             "Interactive search"),
        ]

    def help(self):
        key = self.app.config.keymap.formatKeys
        commands = self.getCommands()
        return [(c[0], key(c[0]), c[1]) for c in commands]

    def __init__(self, app):
        super(TopicListView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('mqtty.view.topic_list')
        self.searchInit()
        self.app = app
        self.unreviewed = True
        self.subscribed = True
        self.project_rows = {}
        self.topic_rows = {}
        self.open_topics = set()
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.refresh()
        self._w.contents.append((self.listbox, ('weight', 1)))

    def selectable(self):
        return True

    def sizing(self):
        return frozenset([urwid.FIXED])

    def refresh(self):
        self.log.debug('refresh called')
        class Topic():
            def __init__(self, key, name):
                self.key = key
                self.name = name

        for key in self.app.db.topics:
            self.log.debug(key)
            self.listbox.body.append(TopicRow(Topic(key, key + "_name")))

    def handleCommands(self, commands):
        self.log.debug('handleCommands called')
        if keymap.REFRESH in commands:
            self.refresh()
            return True


class TopicRow(urwid.Button):
    project_focus_map = {None: 'focused',
                         'subscribed-project': 'focused-subscribed-project',
                         'marked-project': 'focused-marked-project',
    }

    def selectable(self):
        return True

    def _setName(self, name):
        self.topic_name = name
        name = '[[ '+name+' ]]'
        if self.mark:
            name = '%'+name
        else:
            name = ' '+name
        self.name.set_text(name)

    def __init__(self, topic, callback=None):
        super(TopicRow, self).__init__('', on_press=callback,
                                       user_data=(topic.key, topic.name))
        self.mark = False
        self._style = None
        self.topic_key = topic.key
        self.name = urwid.Text('')
        self._setName(topic.name)
        self.name.set_wrap_mode('clip')
        self.unreviewed_changes = urwid.Text(u'', align=urwid.RIGHT)
        self.open_changes = urwid.Text(u'', align=urwid.RIGHT)
        col = urwid.Columns([
                self.name,
                ('fixed', 11, self.unreviewed_changes),
                ('fixed', 5, self.open_changes),
                ])
        self.row_style = urwid.AttrMap(col, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.project_focus_map)
        self._style = 'subscribed-project'
        self.row_style.set_attr_map({None: self._style})
        self.update(topic)

    def update(self, topic, unreviewed_changes=None, open_changes=None):
        self._setName(topic.name)
        if unreviewed_changes is None:
            self.unreviewed_changes.set_text('')
        else:
            self.unreviewed_changes.set_text('%i ' % unreviewed_changes)
        if open_changes is None:
            self.open_changes.set_text('')
        else:
            self.open_changes.set_text('%i ' % open_changes)

    def toggleMark(self):
        self.mark = not self.mark
        if self.mark:
            style = 'marked-project'
        else:
            style = self._style
        self.row_style.set_attr_map({None: style})
        self._setName(self.topic_name)
