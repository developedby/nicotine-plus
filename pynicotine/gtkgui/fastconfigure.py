# COPYRIGHT (C) 2020 Nicotine+ Team
# COPYRIGHT (C) 2016-2017 Michael Labouebe <gfarmerfr@free.fr>
# COPYRIGHT (C) 2009-2011 Quinox <quinox@users.sf.net>
#
# GNU GENERAL PUBLIC LICENSE
#    Version 3, 29 June 2007
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
from gettext import gettext as _
from os.path import exists
from os.path import getsize
from os.path import join

from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

import _thread
from pynicotine.gtkgui.dirchooser import choose_dir
from pynicotine.gtkgui.dialogs import combo_box_dialog
from pynicotine.gtkgui.utils import human_size
from pynicotine.gtkgui.utils import initialise_columns
from pynicotine.gtkgui.utils import open_uri


def dirstats(directory):

    totaldirs = 0
    totalfiles = 0
    totalsize = 0
    extensions = {}

    for root, dirs, files in os.walk(directory):

        totaldirs += len(dirs)
        totalfiles += len(files)

        for f in files:

            try:
                totalsize += getsize(join(root, f))
            except OSError:
                pass

            parts = f.rsplit('.', 1)

            if len(parts) == 2 and len(parts[1]) < 5:

                try:
                    extensions[parts[1]] += 1
                except KeyError:
                    extensions[parts[1]] = 1

    return totaldirs, totalfiles, totalsize, extensions


class FastConfigureAssistant(object):

    def __init__(self, frame):

        self.frame = frame
        self.initphase = True  # don't respond to signals unless False
        self.config = frame.np.config

        builder = Gtk.Builder()

        builder.set_translation_domain('nicotine')
        builder.add_from_file(os.path.join(os.path.dirname(os.path.realpath(__file__)), "ui", "fastconfigure.ui"))

        self.window = builder.get_object("FastConfigureAssistant")
        self.window.set_transient_for(frame.MainWindow)
        builder.connect_signals(self)

        self.kids = {}

        for i in builder.get_objects():
            try:
                self.kids[Gtk.Buildable.get_name(i)] = i
            except TypeError:
                pass

        # Page specific, sharepage
        # The last column is the raw byte/unicode object
        # for the folder (not shown)
        self.sharelist = Gtk.ListStore(
            GObject.TYPE_STRING,
            GObject.TYPE_STRING,
            GObject.TYPE_STRING,
            GObject.TYPE_STRING,
            GObject.TYPE_STRING,
            GObject.TYPE_STRING,
            GObject.TYPE_STRING
        )

        initialise_columns(
            self.kids['shareddirectoriestree'],
            [_("Virtual Directory"), 0, "text"],
            [_("Directory"), 0, "text"],
            [_("Size"), 0, "text"],
            [_("Files"), 0, "text"],
            [_("Dirs"), 0, "text"],
            [_("File types"), 0, "text"]
        )

        self.kids['shareddirectoriestree'].set_model(self.sharelist)
        self.kids['shareddirectoriestree'].get_selection().set_mode(
            Gtk.SelectionMode.MULTIPLE
        )

        self.initphase = False

    def show(self):
        self.initphase = True
        self._populate()
        self.initphase = False
        self.window.show()

    def _populate(self):

        # userpasspage
        self.kids['username'].set_text(
            self.config.sections["server"]["login"]
        )
        self.kids['password'].set_text(
            self.config.sections["server"]["passw"]
        )

        if self.config.sections["server"]["firewalled"]:
            self.kids['portclosed'].set_active(True)
        else:
            self.kids['portopen'].set_active(True)

        self.kids['lowerport'].set_value(
            self.config.sections["server"]["portrange"][0]
        )
        self.kids['upperport'].set_value(
            self.config.sections["server"]["portrange"][1]
        )

        # sharepage
        if self.config.sections['transfers']['downloaddir']:
            self.kids['downloaddir'].set_current_folder(
                self.config.sections['transfers']['downloaddir']
            )

        self.sharelist.clear()

        if self.config.sections["transfers"]["friendsonly"] and \
           self.config.sections["transfers"]["enablebuddyshares"]:
            for directory in self.config.sections["transfers"]["buddyshared"]:
                self.addshareddir(directory)
        else:
            for directory in self.config.sections["transfers"]["shared"]:
                self.addshareddir(directory)

        self.kids['onlysharewithfriends'].set_active(
            self.config.sections["transfers"]["friendsonly"]
        )

        # If the user has a public share and a buddy share
        # we cannot update this from FastConfigure
        # (we only have 1 list of dirs)
        self.caneditshare = (
            not self.config.sections["transfers"]["enablebuddyshares"] or
            self.config.sections["transfers"]["friendsonly"]
        )

        self.kids['onlysharewithfriends'].set_sensitive(self.caneditshare)
        self.kids['addshare'].set_sensitive(self.caneditshare)
        self.kids['removeshares'].set_sensitive(self.caneditshare)
        self.kids['shareddirectoriestree'].set_sensitive(self.caneditshare)

    def store(self):

        # userpasspage
        self.config.sections["server"]["login"] = self.kids['username'].get_text()
        self.config.sections["server"]["passw"] = self.kids['password'].get_text()

        # portpage
        self.config.sections['server']['portrange'] = (
            self.kids['lowerport'].get_value_as_int(),
            self.kids['upperport'].get_value_as_int()
        )
        self.config.sections['server']['firewalled'] = not self.kids['portopen'].get_active()

        # sharepage
        self.config.sections['transfers']['downloaddir'] = self.kids['downloaddir'].get_file().get_path()

        if self.caneditshare:
            self.config.sections["transfers"]["friendsonly"] = self.kids['onlysharewithfriends'].get_active()

            if self.config.sections["transfers"]["friendsonly"] and \
               self.config.sections["transfers"]["enablebuddyshares"]:
                self.config.sections["transfers"]["buddyshared"] = self.getshareddirs()
            else:
                self.config.sections["transfers"]["shared"] = self.getshareddirs()

    def on_close(self, widget):
        self.window.hide()

    def on_apply(self, widget):
        self.store()
        self.window.hide()

        # Rescan public shares if needed
        if not self.config.sections["transfers"]["friendsonly"]:
            self.frame.on_rescan()

        # Rescan buddy shares if needed
        if self.config.sections["transfers"]["enablebuddyshares"]:
            self.frame.on_buddy_rescan()

        if not self.frame.np.active_server_conn:
            self.frame.on_connect(-1)

    def on_cancel(self, widget):
        self.window.hide()

    def resetcompleteness(self, page=None):
        """Turns on the complete flag if everything required is filled in."""

        # Never use self.config.sections here, only self.kids.
        complete = False

        if not page:
            pageid = self.window.get_current_page()
            page = self.window.get_nth_page(pageid)
            if not page:
                return

        name = Gtk.Buildable.get_name(page)

        if name == 'welcomepage':
            complete = True

        elif name == 'userpasspage':
            if (len(self.kids['username'].get_text()) > 0 and len(self.kids['password'].get_text()) > 0):
                complete = True

        elif name == 'portpage':
            if self.kids['portopen'].get_active() or \
               self.kids['portclosed'].get_active():
                complete = True

        elif name == 'sharepage':
            if exists(self.kids['downloaddir'].get_filename()):
                complete = True

        elif name == 'summarypage':

            complete = True
            showcpwarning = (
                self.kids['portclosed'].get_active()
            )

            if showcpwarning:
                self.kids['labelclosedport'].show()
            else:
                self.kids['labelclosedport'].hide()

            shownfwarning = (
                self.kids['onlysharewithfriends'].get_active() or
                len(self.getshareddirs()) == 0
            )

            if shownfwarning:
                self.kids['labelnoshare'].show()
            else:
                self.kids['labelnoshare'].hide()

        self.window.set_page_complete(page, complete)

    def on_prepare(self, widget, page):
        self.window.set_page_complete(page, False)
        self.resetcompleteness(page)

    def on_entry_changed(self, widget, param1=None, param2=None, param3=None):
        self.resetcompleteness()

    def on_entry_paste(self, user_data):
        """
            Hack to workaround if the user paste is username or password.
            The "paste-clipboard" event of the GtkEntry doesn't seems to have a length after a text is pasted into it.
            The "key-press-event" work though...
            So we get the GtkEditable text via it's "changed" event and we set the GtkEntry with it's value.
        """

        # Get the name of the GtkEditable object
        name = Gtk.Buildable.get_name(user_data)

        # Set the text of the corresponding entry
        self.kids[name].set_text(user_data.get_text())

        # Check if the form is complete
        self.resetcompleteness()

    def getshareddirs(self):

        iterator = self.sharelist.get_iter_first()
        dirs = []

        while iterator is not None:
            dirs.append(
                (
                    self.sharelist.get_value(iterator, 0),
                    self.sharelist.get_value(iterator, 6)
                )
            )
            iterator = self.sharelist.iter_next(iterator)

        return dirs

    def addshareddir(self, directory):

        iterator = self.sharelist.get_iter_first()

        while iterator is not None:

            if directory[1] == self.sharelist.get_value(iterator, 6):
                return

            iterator = self.sharelist.iter_next(iterator)

        self.sharelist.append([
            directory[0],
            directory[1],
            "",
            "",
            "",
            _("Counting files..."),
            directory[1]
        ])

        _thread.start_new_thread(self._addsharedir, (directory,))

    def _addsharedir(self, directory):

        subdirs, files, size, extensions = dirstats(directory[1])
        exts = []

        for ext, count in extensions.items():
            exts.append((count, ext))

        exts.sort(reverse=True)
        extstring = ", ".join(
            ["%s %s" % (count, ext) for count, ext in exts[:5]]
        )

        if len(exts) > 5:
            extstring += ", ..."

        GLib.idle_add(
            self._updatedirstats,
            directory,
            human_size(size),
            files,
            subdirs,
            extstring
        )

    def _updatedirstats(self, directory, size, files, subdirs, extensions):

        iterator = self.sharelist.get_iter_first()

        while iterator is not None:

            if directory[1] == self.sharelist.get_value(iterator, 6):

                self.sharelist.insert(0, [
                    directory[0],
                    directory[1],
                    human_size(size),
                    str(files),
                    str(subdirs),
                    extensions,
                    directory[1]
                ])

                self.sharelist.remove(iterator)
                return

            iterator = self.sharelist.iter_next(iterator)

    def on_button_pressed(self, widget):

        if self.initphase:
            return

        name = Gtk.Buildable.get_name(widget)

        if name == "checkmyport":
            open_uri(
                '='.join([
                    'http://tools.slsknet.org/porttest.php?port',
                    str(self.frame.np.waitport)
                ]),
                self.window
            )

        if name == "addshare":

            selected = choose_dir(
                self.window.get_toplevel(),
                title=_("Add a shared directory")
            )

            if selected:

                for directory in selected:

                    virtual = combo_box_dialog(
                        parent=self.frame.MainWindow,
                        title=_("Virtual name"),
                        message=_("Enter virtual name for '%(dir)s':") % {'dir': directory}
                    )

                    # If the virtual name is empty
                    if virtual == '' or virtual is None:

                        dlg = Gtk.MessageDialog(
                            transient_for=self.window,
                            flags=0,
                            type=Gtk.MessageType.WARNING,
                            buttons=Gtk.ButtonsType.OK,
                            text=_("Warning")
                        )
                        dlg.format_secondary_text(_("The chosen virtual name is empty"))
                        dlg.run()
                        dlg.destroy()

                    else:
                        # We get the current defined shares from the treeview
                        model, paths = self.kids['shareddirectoriestree'].get_selection().get_selected_rows()

                        iterator = model.get_iter_first()

                        while iterator is not None:

                            # We reject the share if the virtual share name is already used
                            if virtual == model.get_value(iterator, 0):

                                dlg = Gtk.MessageDialog(
                                    transient_for=self.window,
                                    flags=0,
                                    type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.OK,
                                    text=_("Warning")
                                )
                                dlg.format_secondary_text(_("The chosen virtual name already exists"))
                                dlg.run()
                                dlg.destroy()
                                return

                            # We also reject the share if the directory is already used
                            elif directory == model.get_value(iterator, 6):

                                dlg = Gtk.MessageDialog(
                                    transient_for=self.window,
                                    flags=0,
                                    type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.OK,
                                    text=_("Warning")
                                )
                                dlg.format_secondary_text(_("The chosen directory is already shared"))
                                dlg.run()
                                dlg.destroy()
                                return

                            else:
                                iterator = model.iter_next(iterator)

                        # The share is unique: we can add it
                        self.addshareddir((virtual, directory))

        if name == "removeshares":

            model, paths = self.kids['shareddirectoriestree'].get_selection().get_selected_rows()
            refs = [Gtk.TreeRowReference(model, x) for x in paths]

            for i in refs:
                self.sharelist.remove(self.sharelist.get_iter(i.get_path()))

        self.resetcompleteness()

    def on_toggled(self, widget):

        if self.initphase:
            return

        self.resetcompleteness()

    def on_spinbutton_change_value(self, widget, scrolltype):

        if self.initphase:
            return

        self.resetcompleteness()

    def on_spinbutton_value_changed(self, widget):

        if self.initphase:
            return

        name = Gtk.Buildable.get_name(widget)

        if name == "lowerport":
            if widget.get_value() > self.kids['upperport'].get_value():
                self.kids['upperport'].set_value(widget.get_value())
        if name == "upperport":
            if widget.get_value() < self.kids['lowerport'].get_value():
                self.kids['lowerport'].set_value(widget.get_value())

        self.resetcompleteness()
