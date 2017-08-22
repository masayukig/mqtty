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

import json
import logging
import pprint
import urwid

from mqtty import keymap
from mqtty import mywid
from mqtty.view import mouse_scroll_decorator

class MessageBox(mywid.HyperText):
    def __init__(self, app, message):
        self.app = app
        self.log = logging.getLogger('mqtty.view.messagebox')
        super(MessageBox, self).__init__(message)

    def set_text(self, text):
        text = [text]
        super(MessageBox, self).set_text(text)

    def search(self, search, attribute):
        self.log.debug("search called ===============")
        return self.text.search(search, attribute)


@mouse_scroll_decorator.ScrollByWheel
class MessageView(urwid.WidgetWrap, mywid.Searchable):
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

    def __init__(self, app, message):
        super(MessageView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('mqtty.view.message')
        self.searchInit()
        self.app = app
        self.message = message
        self.messagebox = MessageBox(app, u'')
        self.grid = mywid.MyGridFlow([self.messagebox],
                                     cell_width=380, h_sep=1, v_sep=1, align='left')
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self._w.contents.append((self.app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(),('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self.listbox.body.append(self.grid)

        self.refresh()
        self._w.set_focus(2)

    def keypress(self, size, key):
        if self.searchKeypress(size, key):
            return None

        if not self.app.input_buffer:
            key = super(MessageView, self).keypress(size, key)
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
        if keymap.INTERACTIVE_SEARCH in commands:
            self.searchStart()
            return True

    def selectable(self):
        return True

    def sizing(self):
        return frozenset([urwid.FIXED])

    def refresh(self):
        self.log.debug('message refresh called ===============')
        self.log.debug('message: ' + self.message.message)
        message = pprint.pformat(json.loads(self.message.message), width=80)

        self.messagebox.set_text(message)

        self.title = "Message: " + str(self.message.key)
        self.app.status.update(title=self.title)
