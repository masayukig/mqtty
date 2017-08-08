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

import argparse
import datetime
import dateutil
import fcntl
import functools
import logging
import os
import re
import socket
import subprocess
import sys
import textwrap
import threading
import warnings
import webbrowser

import six
from six.moves import queue
from six.moves.urllib import parse as urlparse
import sqlalchemy.exc
import urwid

from mqtty import db
from mqtty import config
from mqtty import keymap
from mqtty import mywid
from mqtty import sync
import mqtty.view
from mqtty.view import mouse_scroll_decorator
#from mqtty.view import message_list as view_message_list
from mqtty.view import topic_list as view_topic_list
import mqtty.version

WELCOME_TEXT = """\
Welcome to Mqtty!

To get started, you should subscribe to some projects.  Press the "L"
key (shift-L) to list all the projects, navigate to the ones you are
interested in, and then press "s" to subscribe to them.  Mqtty will
automatically sync stories in your subscribed projects.

Press the F1 key anywhere to get help.  Your terminal emulator may
require you to press function-F1 or alt-F1 instead.

"""

class StatusHeader(urwid.WidgetWrap):
    def __init__(self, app):
        super(StatusHeader, self).__init__(urwid.Columns([]))
        self.app = app
        self.title_widget = urwid.Text(u'Start')
        self.error_widget = urwid.Text('')
        self.offline_widget = urwid.Text('')
        self.sync_widget = urwid.Text(u'Sync: 0')
        self.held_widget = urwid.Text(u'')
        self._w.contents.append((self.title_widget, ('pack', None, False)))
        self._w.contents.append((urwid.Text(u''), ('weight', 1, False)))
        self._w.contents.append((self.held_widget, ('pack', None, False)))
        self._w.contents.append((self.error_widget, ('pack', None, False)))
        self._w.contents.append((self.offline_widget, ('pack', None, False)))
        self._w.contents.append((self.sync_widget, ('pack', None, False)))
        self.error = None
        self.offline = None
        self.title = None
        self.message = None
        self.sync = None
        self.held = None
        self._error = False
        self._offline = False
        self._title = ''
        self._message = ''
        self._sync = 0
        self._held = 0
        self.held_key = self.app.config.keymap.formatKeys(keymap.LIST_HELD)

    def update(self, title=None, message=None, error=None,
               offline=None, refresh=True, held=None):
        if title is not None:
            self.title = title
        if message is not None:
            self.message = message
        if error is not None:
            self.error = error
        if offline is not None:
            self.offline = offline
        if held is not None:
            self.held = held
        self.sync = self.app.sync.queue.qsize()
        if refresh:
            self.refresh()

    def refresh(self):
        if (self._title != self.title or self._message != self.message):
            self._title = self.title
            self._message = self.message
            t = self.message or self.title
            self.title_widget.set_text(t)
        if self._held != self.held:
            self._held = self.held
            if self._held:
                self.held_widget.set_text(('error', u'Held: %s (%s)' % (self._held, self.held_key)))
            else:
                self.held_widget.set_text(u'')
        if self._error != self.error:
            self._error = self.error
            if self._error:
                self.error_widget.set_text(('error', u' Error'))
            else:
                self.error_widget.set_text(u'')
        if self._offline != self.offline:
            self._offline = self.offline
            if self._offline:
                self.offline_widget.set_text(u' Offline')
            else:
                self.offline_widget.set_text(u'')
        if self._sync != self.sync:
            self._sync = self.sync
            self.sync_widget.set_text(u' Sync: %i' % self._sync)


class BreadCrumbBar(urwid.WidgetWrap):
    BREADCRUMB_SYMBOL = u'\N{BLACK RIGHT-POINTING SMALL TRIANGLE}'
    BREADCRUMB_WIDTH = 25

    def __init__(self):
        self.prefix_text = urwid.Text(u' \N{WATCH}  ')
        self.breadcrumbs = urwid.Columns([], dividechars=3)
        self.display_widget = urwid.Columns(
            [('pack', self.prefix_text), self.breadcrumbs])
        super(BreadCrumbBar, self).__init__(self.display_widget)

    def _get_breadcrumb_text(self, screen):
        title = getattr(screen, 'short_title', None)
        if not title:
            title = getattr(screen, 'title', str(screen))
        text = "%s %s" % (BreadCrumbBar.BREADCRUMB_SYMBOL, title)
        if len(text) > 23:
            text = "%s..." % text[:20]
        return urwid.Text(text, wrap='clip')

    def _get_breadcrumb_column_options(self):
        return self.breadcrumbs.options("given", BreadCrumbBar.BREADCRUMB_WIDTH)

    def _update(self, screens):
        breadcrumb_contents = []
        for screen in screens:
            breadcrumb_contents.append((
                self._get_breadcrumb_text(screen),
                self._get_breadcrumb_column_options()))
        self.breadcrumbs.contents = breadcrumb_contents
        # Update focus so we always have the right end of the breadcrumb trail
        # in view. Urwid will gracefully handle clipping from the left when
        # there is overflow.as trail grows, shrinks, or screen is resized.
        if len(self.breadcrumbs.contents):
            self.breadcrumbs.focus_position = len(self.breadcrumbs.contents) - 1


class SearchDialog(mywid.ButtonDialog):
    signals = ['search', 'cancel']
    def __init__(self, app, default):
        self.app = app
        search_button = mywid.FixedButton('Search')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(search_button, 'click',
                             lambda button:self._emit('search'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        super(SearchDialog, self).__init__("Search",
                                           "Enter a change number or search string.",
                                           entry_prompt="Search: ",
                                           entry_text=default,
                                           buttons=[search_button,
                                                    cancel_button],
                                           ring=app.ring)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(SearchDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.ACTIVATE in commands:
            self._emit('search')
            return None
        return key

# From: cpython/file/2.7/Lib/webbrowser.py with modification to
# redirect stdin/out/err.
class BackgroundBrowser(webbrowser.GenericBrowser):
    """Class for all browsers which are to be started in the
       background."""

    def open(self, url, new=0, autoraise=True):
        cmdline = [self.name] + [arg.replace("%s", url)
                                 for arg in self.args]
        inout = file(os.devnull, "r+")
        try:
            if sys.platform[:3] == 'win':
                p = subprocess.Popen(cmdline)
            else:
                setsid = getattr(os, 'setsid', None)
                if not setsid:
                    setsid = getattr(os, 'setpgrp', None)
                p = subprocess.Popen(cmdline, close_fds=True,
                                     stdin=inout, stdout=inout,
                                     stderr=inout, preexec_fn=setsid)
            return (p.poll() is None)
        except OSError:
            return False

class ProjectCache(object):
    def __init__(self):
        self.projects = {}

    def get(self, project):
        if project.key not in self.projects:
            self.projects[project.key] = dict(
                active_stories = len(project.active_stories),
                stories = len(project.stories),
            )
        return self.projects[project.key]

    def clear(self, project):
        if project.key in self.projects:
            del self.projects[project.key]

class App(object):
    simple_story_search = re.compile('^(\d+)$')

    def __init__(self, server=None, palette='default',
                 keymap='default', debug=False, verbose=False,
                 disable_sync=False, disable_background_sync=False,
                 fetch_missing_refs=False,
                 path=config.DEFAULT_CONFIG_PATH):
        self.server = server
        self.config = config.Config(server, palette, keymap, path)
        if debug:
            level = logging.DEBUG
        elif verbose:
            level = logging.INFO
        else:
            level = logging.WARNING
        logging.basicConfig(filename=self.config.log_file, filemode='w',
                            format='%(asctime)s %(message)s',
                            level=level)
        # Python2.6 Logger.setLevel doesn't convert string name
        # to integer code. Here, we set the requests logger level to
        # be less verbose, since our logging output duplicates some
        # requests logging content in places.
        req_level_name = 'WARN'
        req_logger = logging.getLogger('requests')
        if sys.version_info < (2, 7):
            level = logging.getLevelName(req_level_name)
            req_logger.setLevel(level)
        else:
            req_logger.setLevel(req_level_name)
        self.log = logging.getLogger('mqtty.App')
        self.log.debug("Starting")

        self.lock_fd = open(self.config.lock_file, 'w')
        try:
            fcntl.lockf(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            print("error: another instance of mqtty is running for: %s" % self.config.server['name'])
            sys.exit(1)

        self.project_cache = ProjectCache()
        self.ring = mywid.KillRing()
        self.input_buffer = []
        webbrowser.register('xdg-open', None, BackgroundBrowser("xdg-open"))

        self.fetch_missing_refs = fetch_missing_refs
        self.config.keymap.updateCommandMap()
        # self.search = search.SearchCompiler(self.config.username)
        self.search = None
        self.db = db.Database(self, self.config.dburi, self.search)
        self.sync = sync.Sync(self, disable_background_sync)

        self.status = StatusHeader(self)
        self.header = urwid.AttrMap(self.status, 'header')
        self.screens = urwid.MonitoredList()
        self.breadcrumbs = BreadCrumbBar()
        self.screens.set_modified_callback(
            functools.partial(self.breadcrumbs._update, self.screens))
        if self.config.breadcrumbs:
            self.footer = urwid.AttrMap(self.breadcrumbs, 'footer')
        else:
            self.footer = None

        screen = view_topic_list.TopicListView(self)
        self.status.update(title=screen.title)
        self.updateStatusQueries()
        self.frame = urwid.Frame(body=screen, footer=self.footer)
        self.loop = urwid.MainLoop(self.frame, palette=self.config.palette.getPalette(),
                                   handle_mouse=self.config.handle_mouse,
                                   unhandled_input=self.unhandledInput,
                                   input_filter=self.inputFilter)

        self.sync_pipe = self.loop.watch_pipe(self.refresh)
        self.error_queue = queue.Queue()
        self.error_pipe = self.loop.watch_pipe(self._errorPipeInput)
        self.logged_warnings = set()
        self.command_pipe = self.loop.watch_pipe(self._commandPipeInput)
        self.command_queue = queue.Queue()

        warnings.showwarning = self._showWarning

        has_subscribed_projects = False
        # FIXME: add a feature to subscribe topics
        # with self.db.getSession() as session:
        #     if session.getProjects(subscribed=True):
        #         has_subscribed_projects = True
        if not has_subscribed_projects:
            self.welcome()

        self.loop.screen.tty_signal_keys(start='undefined', stop='undefined')
        #self.loop.screen.set_terminal_properties(colors=88)

        self.startSocketListener()

        if not disable_sync:
            self.sync_thread = threading.Thread(target=self.sync.run, args=(self.sync_pipe,))
            self.sync_thread.daemon = True
            self.sync_thread.start()
        else:
            self.sync_thread = None
            self.sync.offline = True
            self.status.update(offline=True)

    def run(self):
        try:
            self.loop.run()
        except KeyboardInterrupt:
            pass

    def _quit(self, widget=None):
        raise urwid.ExitMainLoop()

    def quit(self):
        dialog = mywid.YesNoDialog(u'Quit',
                                   u'Are you sure you want to quit?')
        urwid.connect_signal(dialog, 'no', self.backScreen)
        urwid.connect_signal(dialog, 'yes', self._quit)

        self.popup(dialog)

    def startSocketListener(self):
        if os.path.exists(self.config.socket_path):
            os.unlink(self.config.socket_path)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.config.socket_path)
        self.socket.listen(1)
        self.socket_thread = threading.Thread(target=self._socketListener)
        self.socket_thread.daemon = True
        self.socket_thread.start()

    def _socketListener(self):
        while True:
            try:
                s, addr = self.socket.accept()
                self.log.debug("Accepted socket connection %s" % (s,))
                buf = ''
                while True:
                    buf += s.recv(1)
                    if buf[-1] == '\n':
                        break
                buf = buf.strip()
                self.log.debug("Received %s from socket" % (buf,))
                s.close()
                parts = buf.split()
                self.command_queue.put((parts[0], parts[1:]))
                os.write(self.command_pipe, six.b('command\n'))
            except Exception:
                self.log.exception("Exception in socket handler")

    def clearInputBuffer(self):
        if self.input_buffer:
            self.input_buffer = []
            self.status.update(message='')

    def changeScreen(self, widget, push=True):
        self.log.debug("Changing screen to %s" % (widget,))
        self.status.update(error=False, title=widget.title)
        if push:
            self.screens.append(self.frame.body)
        self.clearInputBuffer()
        self.frame.body = widget

    def backScreen(self, target_widget=None):
        if not self.screens:
            return
        while self.screens:
            self.log.debug("screens %s" % (target_widget,))
            widget = self.screens.pop()
            if (not target_widget) or (widget is target_widget):
                break
        self.log.debug("Popping screen to %s" % (widget,))
        if hasattr(widget, 'title'):
            self.status.update(title=widget.title)
        self.clearInputBuffer()
        self.frame.body = widget
        self.refresh(force=True)

    def findStoryList(self):
        for widget in reversed(self.screens):
            if isinstance(widget, view_story_list.StoryListView):
                return widget
        return None

    def clearHistory(self):
        self.log.debug("Clearing screen history")
        while self.screens:
            widget = self.screens.pop()
            self.clearInputBuffer()
            self.frame.body = widget

    def refresh(self, data=None, force=False):
        self.log.debug("app.refresh called =============")
        widget = self.frame.body
        while isinstance(widget, urwid.Overlay):
            widget = widget.contents[0][0]
        interested = force
        invalidate = False
        try:
            while True:
                event = self.sync.result_queue.get(0)
                if widget.interested(event):
                    interested = True
                if hasattr(event, 'held_changed') and event.held_changed:
                    invalidate = True
        except queue.Empty:
            pass
        if interested:
            widget.refresh()
        if invalidate:
            self.updateStatusQueries()
        self.status.refresh()

    def updateStatusQueries(self):
        return

    def popup(self, widget,
              relative_width=50, relative_height=25,
              min_width=20, min_height=8,
              width=None, height=None):
        self.clearInputBuffer()
        if width is None:
            width = ('relative', relative_width)
        if height is None:
            height = ('relative', relative_height)
        overlay = urwid.Overlay(widget, self.frame.body,
                                'center', width,
                                'middle', height,
                                min_width=min_width, min_height=min_height)
        if hasattr(widget, 'title'):
            overlay.title = widget.title
        self.log.debug("Overlaying %s on screen %s" % (widget, self.frame.body))
        self.screens.append(self.frame.body)
        self.frame.body = overlay

    def getGlobalCommands(self):
        return list(mywid.GLOBAL_HELP)

    def getGlobalHelp(self):
        keys =  [(k, self.config.keymap.formatKeys(k), t) for (k, t) in self.getGlobalCommands()]
        for d in self.config.dashboards.values():
            keys.append(('', d['key'], d['name']))
        return keys

    def help(self):
        if not hasattr(self.frame.body, 'help'):
            return
        global_help = self.getGlobalHelp()
        parts = [('Global Keys', global_help),
                 ('This Screen', self.frame.body.help())]
        keylen = 0
        for title, items in parts:
            for cmd, keys, text in items:
                keylen = max(len(keys), keylen)
        text = ''
        for title, items in parts:
            if text:
                text += '\n'
            text += title+'\n'
            text += '%s\n' % ('='*len(title),)
            for cmd, keys, cmdtext in items:
                text += '{keys:{width}} {text}\n'.format(
                    keys=keys, width=keylen, text=cmdtext)
        dialog = mywid.MessageDialog('Help for %s' % version(), text)
        lines = text.split('\n')
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_width=76, min_height=len(lines)+4)

    def welcome(self):
        text = WELCOME_TEXT
        dialog = mywid.MessageDialog('Welcome', text)
        lines = text.split('\n')
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_width=76, min_height=len(lines)+4)


    def searchDialog(self, default):
        dialog = SearchDialog(self, default)
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.backScreen())
        urwid.connect_signal(dialog, 'search',
            lambda button: self._searchDialog(dialog))
        self.popup(dialog, min_width=76, min_height=8)

    def _searchDialog(self, dialog):
        self.backScreen()
        query = dialog.entry.edit_text.strip()
        if self.simple_story_search.match(query):
            query = 'story:%s' % query
        else:
            result = self.parseInternalURL(query)
            if result is not None:
                return self.openInternalURL(result)
        self.doSearch(query)

    def error(self, message, title='Error'):
        dialog = mywid.MessageDialog(title, message)
        urwid.connect_signal(dialog, 'close',
                             lambda button: self.backScreen())

        cols, rows = self.loop.screen.get_cols_rows()
        cols = int(cols*.5)
        lines = textwrap.wrap(message, cols)
        min_height = max(4, len(lines)+4)

        self.popup(dialog, min_height=min_height)
        return None

    def inputFilter(self, keys, raw):
        if 'window resize' in keys:
            m = getattr(self.frame.body, 'onResize', None)
            if m:
                m()
        return keys

    def unhandledInput(self, key):
        # get commands from buffer
        keys = self.input_buffer + [key]
        commands = self.config.keymap.getCommands(keys)
        if keymap.PREV_SCREEN in commands:
            self.backScreen()
        elif keymap.TOP_SCREEN in commands:
            self.clearHistory()
            self.refresh(force=True)
        elif keymap.HELP in commands:
            self.help()
        elif keymap.QUIT in commands:
            self.quit()
        elif keymap.FURTHER_INPUT in commands:
            self.input_buffer.append(key)
            msg = ''.join(self.input_buffer)
            commands = dict(self.getGlobalCommands())
            if hasattr(self.frame.body, 'getCommands'):
                commands.update(dict(self.frame.body.getCommands()))
            further_commands = self.config.keymap.getFurtherCommands(keys)
            completions = []
            for (key, cmds) in further_commands:
                for cmd in cmds:
                    if cmd in commands:
                        completions.append(key)
            completions = ' '.join(completions)
            msg = '%s: %s' % (msg, completions)
            self.status.update(message=msg)
            return
        self.clearInputBuffer()

    def openURL(self, url):
        self.log.debug("Open URL %s" % url)
        webbrowser.open_new_tab(url)
        self.loop.screen.clear()

    def time(self, dt):
        if dt is None:
            return None
        utc = dt.replace(tzinfo=dateutil.tz.tzutc())
        if self.config.utc:
            return utc
        local = utc.astimezone(dateutil.tz.tzlocal())
        return local

    def _errorPipeInput(self, data=None):
        (title, message) = self.error_queue.get()
        self.error(message, title=title)

    def _showWarning(self, message, category, filename, lineno,
                     file=None, line=None):
        # Don't display repeat warnings
        if str(message) in self.logged_warnings:
            return
        m = warnings.formatwarning(message, category, filename, lineno, line)
        self.log.warning(m)
        self.logged_warnings.add(str(message))
        # Log this warning, but never display it to the user; it is
        # nearly un-actionable.
        if category == requestsexceptions.InsecurePlatformWarning:
            return
        if category == requestsexceptions.SNIMissingWarning:
            return
        # Disable InsecureRequestWarning when certificate validation is disabled
        if not self.config.verify_ssl:
            if category == requestsexceptions.InsecureRequestWarning:
                return
        self.error_queue.put(('Warning', m))
        os.write(self.error_pipe, six.b('error\n'))

    def _commandPipeInput(self, data=None):
        (command, data) = self.command_queue.get()
        if command == 'open':
            url = data[0]
            self.log.debug("Opening URL %s" % (url,))
            result = self.parseInternalURL(url)
            if result is not None:
                self.openInternalURL(result)
        else:
            self.log.error("Unable to parse command %s with data %s" % (command, data))


def version():
    return "Mqtty version: %s" % mqtty.version.version_info.release_string()

class PrintKeymapAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        for cmd in sorted(keymap.DEFAULT_KEYMAP.keys()):
            print(cmd.replace(' ', '-'))
        sys.exit(0)

class PrintPaletteAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        for attr in sorted(palette.DEFAULT_PALETTE.keys()):
            print(attr)
        sys.exit(0)

class OpenChangeAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        cf = config.Config(namespace.server, namespace.palette,
                           namespace.keymap, namespace.path)
        url = values[0]
        result = urlparse.urlparse(values[0])
        if not url.startswith(cf.url):
            print('Supplied URL must start with %s' % (cf.url,))
            sys.exit(1)

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(cf.socket_path)
        s.sendall('open %s\n' % url)
        sys.exit(0)

def main():
    parser = argparse.ArgumentParser(
        description='Console client for MQTTY')
    parser.add_argument('-c', dest='path',
                        default=config.DEFAULT_CONFIG_PATH,
                        help='path to config file')
    parser.add_argument('-v', dest='verbose', action='store_true',
                        help='enable more verbose logging')
    parser.add_argument('-d', dest='debug', action='store_true',
                        help='enable debug logging')
    parser.add_argument('--no-sync', dest='no_sync', action='store_true',
                        help='disable remote syncing')
    parser.add_argument('--debug-sync', dest='debug_sync', action='store_true',
                        help='disable most background sync tasks for debugging')
    parser.add_argument('--fetch-missing-refs', dest='fetch_missing_refs',
                        action='store_true',
                        help='fetch any refs missing from local repos')
    parser.add_argument('--print-keymap', nargs=0, action=PrintKeymapAction,
                        help='print the keymap command names to stdout')
    parser.add_argument('--print-palette', nargs=0, action=PrintPaletteAction,
                        help='print the palette attribute names to stdout')
    parser.add_argument('--open', nargs=1, action=OpenChangeAction,
                        metavar='URL',
                        help='open the given URL in a running Boardtty')
    parser.add_argument('--version', dest='version', action='version',
                        version=version(),
                        help='show Mqtty\'s version')
    parser.add_argument('-p', dest='palette', default='default',
                        help='color palette to use')
    parser.add_argument('-k', dest='keymap', default='default',
                        help='keymap to use')
    parser.add_argument('server', nargs='?',
                        help='the server to use (as specified in config file)')
    args = parser.parse_args()
    g = App(args.server, args.palette, args.keymap, args.debug, args.verbose,
            args.no_sync, args.debug_sync, args.fetch_missing_refs, args.path)
    g.run()


if __name__ == '__main__':
    main()
