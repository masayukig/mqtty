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
from mqtty.view import message as view_message
from mqtty.view import mouse_scroll_decorator


class MessageListHeader(urwid.WidgetWrap):
    def __init__(self):
        cols = [(5, urwid.Text(u' #')),
                 urwid.Text(u'Message'),
                 (10, urwid.Text(u'Updated')),
        ]
        super(MessageListHeader, self).__init__(urwid.Columns(cols))


@mouse_scroll_decorator.ScrollByWheel
class MessageListView(urwid.WidgetWrap, mywid.Searchable):
    title = "Message"
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
            (keymap.INTERACTIVE_SEARCH,
             "Interactive search"),
        ]

    def help(self):
        key = self.app.config.keymap.formatKeys
        commands = self.getCommands()
        return [(c[0], key(c[0]), c[1]) for c in commands]

    def __init__(self, app, topic):
        super(MessageListView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('mqtty.view.message_list')
        self.searchInit()
        self.app = app
        self.topic = topic
        self.message_rows = {}
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.refresh()
        self.header = MessageListHeader()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(),('pack', 1)))
        self._w.contents.append((urwid.AttrWrap(self.header, 'table-header'), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))

    def selectable(self):
        return True

    def sizing(self):
        return frozenset([urwid.FIXED])

    def refresh(self):
        self.log.debug('message_list refresh called ===============')

        len(self.listbox.body)
        i = 0
        with self.app.db.getSession() as session:
            for message in session.getMessagesByTopic(self.topic):
                key = message.key
                row = self.message_rows.get(key)
                if not row:
                    row = MessageRow(message, self.onSelect)
                    self.listbox.body.append(row)
                    self.message_rows[key] = row
                else:
                    row.update(message)
                i = i + 1

        self.title = "Messages: " + str(i)
        self.app.status.update(title=self.title)

    def onSelect(self, button, data):
        message = data
        self.app.changeScreen(view_message.MessageView(
            self.app, message))


class MessageListColumns(object):
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


class MessageRow(urwid.Button):
    message_focus_map = {None: 'focused',
                         # 'focused-message': 'focused-subscribed-project',
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

    def __init__(self, message, callback=None):
        super(MessageRow, self).__init__('', on_press=callback,
                                         user_data=(message))
        self.mark = False
        self._style = None
        self.message_key = urwid.Text(u'', align=urwid.RIGHT) # message.key
        self.name = urwid.Text('')
        self._setName(message.message)
        self.updated = urwid.Text(u'', align=urwid.RIGHT)
        self.name.set_wrap_mode('clip')
        col = urwid.Columns([
                ('fixed', 5, self.message_key),
                self.name,
                ('fixed', 10, self.updated),
                ])
        self.row_style = urwid.AttrMap(col, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.message_focus_map)
        self._style = None # 'focused-message'
        self.row_style.set_attr_map({None: self._style})
        self.update(message)

    def update(self, message):
        self.message_key.set_text('%i ' % message.key)
        self.updated.set_text(str(message.updated))
        # self._setName(str(message.key) + " " + message.message)
