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

from mqtty import keymap
from mqtty import mywid
from mqtty.view import message_list as view_message_list
from mqtty.view import mouse_scroll_decorator


class ColumnInfo(object):
    def __init__(self, name, packing, value):
        self.name = name
        self.packing = packing
        self.value = value
        self.options = (packing, value)
        if packing == 'given':
            self.spacing = value + 1
        else:
            self.spacing = (value * 8) + 1


COLUMNS = [
    ColumnInfo('No.',  'given',   5),
    ColumnInfo('Topic',   'weight',  1),
    ColumnInfo('Updated', 'given',  20),
    ColumnInfo('# of MSG', 'given',   9),
]

class TopicListHeader(urwid.WidgetWrap):
    def __init__(self):
        cols = [(5, urwid.Text(u' No.')),
                 urwid.Text(u' Topic'),
                 (20, urwid.Text(u'Updated')),
                 (9,  urwid.Text(u'# of MSG')),
        ]
        super(TopicListHeader, self).__init__(urwid.Columns(cols))


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
        self.reverse = False
        self.project_rows = {}
        self.topic_rows = {}
        self.open_topics = set()
        self.sort_by = 'name'
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.refresh()
        self.header = TopicListHeader()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(),('pack', 1)))
        self._w.contents.append((urwid.AttrWrap(self.header, 'table-header'), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(3)

    def selectable(self):
        return True

    def sizing(self):
        return frozenset([urwid.FIXED])

    def refresh(self):
        self.log.debug('topic_list refresh called ===============')

        len(self.listbox.body)
        # for row in self.listbox.body:
        #     self.listbox.body.remove(row)
        i = 0
        with self.app.db.getSession() as session:
            topic_list = session.getTopics(sort_by=self.sort_by)
            if self.reverse:
                topic_list.reverse()
            for topic in topic_list:
                num_msg = len(session.getMessagesByTopic(topic))
                key = topic.key
                row = self.topic_rows.get(key)
                if not row:
                    row = TopicRow(topic, num_msg, self.onSelect)
                    self.listbox.body.append(row)
                    self.topic_rows[key] = row
                else:
                    row.update(topic, num_msg)
                i = i + 1

        self.title = "Topics: " + str(i)
        self.app.status.update(title=self.title)


#            if i > 0:
#                self.listbox.body.pop()
        # for key in self.app.db.topics:
        #     self.log.debug(key)
        #     self.listbox.body.append(TopicRow(Topic(key, key + "_name")))

    def clearTopicList(self):
        for key, value in self.topic_rows.items():
            self.listbox.body.remove(value)
        self.topic_rows = {}

    def keypress(self, size, key):
        if self.searchKeypress(size, key):
            return None

        if not self.app.input_buffer:
            key = super(TopicListView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        ret = self.handleCommands(commands)
        if ret is True:
            if keymap.FURTHER_INPUT not in commands:
                self.app.clearInputBuffer()
            return None
        return key

    def handleCommands(self, commands):
        self.log.debug('handleCommands called')
        if keymap.REFRESH in commands:
            self.refresh()
            self.app.status.update()
            return True
        if keymap.SORT_BY_NUMBER in commands:
            if not len(self.listbox.body):
                return True
            self.sort_by = 'key'
            self.clearTopicList()
            self.refresh()
            return True
        if keymap.SORT_BY_UPDATED in commands:
            if not len(self.listbox.body):
                return True
            self.sort_by = 'updated'
            self.clearTopicList()
            self.refresh()
            return True
        if keymap.SORT_BY_TOPIC in commands:
            if not len(self.listbox.body):
                return True
            self.sort_by = 'name'
            self.clearTopicList()
            self.refresh()
            return True
        if keymap.SORT_BY_REVERSE in commands:
            if not len(self.listbox.body):
                return True
            if self.reverse:
                self.reverse = False
            else:
                self.reverse = True
            self.clearTopicList()
            self.refresh()
            return True

    def onSelect(self, button, data):
        topic = data
        self.app.changeScreen(view_message_list.MessageListView(
            self.app, topic))


class TopicListColumns(object):
    def updateColumns(self):
        del self.columns.contents[:]
        cols = self.columns.contents
        options = self.columns.options

        for colinfo in COLUMNS:
            if colinfo.name in self.enabled_columns:
                attr = colinfo.name.lower().replace(' ', '_')
                cols.append((getattr(self, attr),
                             options(*colinfo.options)))

        for c in self.category_columns:
            cols.append(c)


class TopicRow(urwid.Button, TopicListColumns):
    topic_focus_map = {None: 'focused',
#                         'subscribed-project': 'focused-subscribed-project',
#                         'marked-project': 'focused-marked-project',
    }

    def selectable(self):
        return True

    def _setName(self, name):
        self.topic_name = name
        name = name
        if self.mark:
            name = '%'+name
        else:
            name = ' '+name
        self.name.set_text(name)

    def __init__(self, topic, num_msg, callback=None):
        super(TopicRow, self).__init__('', on_press=callback,
                                       user_data=(topic))
        self.mark = False
        self._style = None
        #self.topic_key = topic.key
        self.name = urwid.Text('')

        self._setName(topic.name)
        # FIXME: showing 'topic_key' is just for debugging. This should be removed.
        self.topic_key = urwid.Text(u'', align=urwid.RIGHT)
        self.name.set_wrap_mode('clip')
        self.updated = urwid.Text(u'', align=urwid.RIGHT)
        self.num_msg = urwid.Text(u'', align=urwid.RIGHT)
        col = urwid.Columns([
            ('fixed', 5, self.topic_key),
            self.name,
            ('fixed', 20, self.updated),
            ('fixed', 9, self.num_msg),
        ])
        self.row_style = urwid.AttrMap(col, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.topic_focus_map)
        self._style = None # 'subscribed-project'
        self.row_style.set_attr_map({None: self._style})
        # self.num_msg = num_msg
        self.update(topic, num_msg)

    def update(self, topic, num_msg):
        # FIXME: showing 'topic_key' is just for debugging. This should be removed.
        self.topic_key.set_text('%i ' % topic.key)
        self.updated.set_text(str(topic.updated))
        self.num_msg.set_text('%i ' % num_msg)
        #self._setName(str(topic.key) + " " + topic.name + " " + str(num_msg))

    def toggleMark(self):
        self.mark = not self.mark
        if self.mark:
            style = 'marked-topic'
        else:
            style = self._style
        self.row_style.set_attr_map({None: style})
        self._setName(self.topic_name)
