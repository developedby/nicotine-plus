# COPYRIGHT (C) 2020 Nicotine+ Team
# COPYRIGHT (C) 2016-2017 Michael Labouebe <gfarmerfr@free.fr>
# COPYRIGHT (C) 2016 Mutnick <muhing@yahoo.com>
# COPYRIGHT (C) 2009-2011 Quinox <quinox@users.sf.net>
# COPYRIGHT (C) 2009 Daelstorm <daelstorm@gmail.com>
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
import pickle
import re
import shelve
import stat
import string
import sys
import taglib
import _thread

from gettext import gettext as _

from pynicotine import slskmessages
from pynicotine.logfacility import log

if sys.platform == "win32":
    # Use semidbm for faster shelves on Windows

    def shelve_open_semidbm(filename, flag='c', protocol=None, writeback=False):
        import semidbm
        return shelve.Shelf(semidbm.open(filename, flag), protocol, writeback)

    shelve.open = shelve_open_semidbm


class Shares:

    def __init__(self, np, config, queue, ui_callback=None):
        self.np = np
        self.ui_callback = ui_callback
        self.config = config
        self.queue = queue
        self.translatepunctuation = str.maketrans(dict.fromkeys(string.punctuation, ' '))

        self.convert_shares()
        self.load_shares(
            [
                ("sharedfiles", os.path.join(self.config.data_dir, "files.db")),
                ("bsharedfiles", os.path.join(self.config.data_dir, "buddyfiles.db")),
                ("sharedfilesstreams", os.path.join(self.config.data_dir, "streams.db")),
                ("bsharedfilesstreams", os.path.join(self.config.data_dir, "buddystreams.db")),
                ("wordindex", os.path.join(self.config.data_dir, "wordindex.db")),
                ("bwordindex", os.path.join(self.config.data_dir, "buddywordindex.db")),
                ("fileindex", os.path.join(self.config.data_dir, "fileindex.db")),
                ("bfileindex", os.path.join(self.config.data_dir, "buddyfileindex.db")),
                ("sharedmtimes", os.path.join(self.config.data_dir, "mtimes.db")),
                ("bsharedmtimes", os.path.join(self.config.data_dir, "buddymtimes.db"))
            ]
        )

        self.compressed_shares_buddy = self.compressed_shares_normal = None

        if not self.config.sections["transfers"]["friendsonly"]:
            self.compress_shares("normal")

        if self.config.sections["transfers"]["enablebuddyshares"]:
            self.compress_shares("buddy")

        self.newbuddyshares = self.newnormalshares = False

    """ Shares-related actions """

    def real2virtual(self, path):
        path = os.path.normpath(path)

        for (virtual, real) in self._virtualmapping():
            real = os.path.normpath(real)

            if path == real:
                return virtual
            if path.startswith(real + os.sep):
                virtualpath = virtual + '\\' + path[len(real + os.sep):].replace(os.sep, '\\')
                return virtualpath
        return "__INTERNAL_ERROR__" + path

    def virtual2real(self, path):
        path = os.path.normpath(path)

        for (virtual, real) in self._virtualmapping():
            virtual = os.path.normpath(virtual)

            if path == virtual:
                return real
            if path.startswith(virtual + '\\'):
                realpath = real + path[len(virtual):].replace('\\', os.sep)
                return realpath
        return "__INTERNAL_ERROR__" + path

    def _virtualmapping(self):

        mapping = self.config.sections["transfers"]["shared"][:]

        if self.config.sections["transfers"]["enablebuddyshares"]:
            mapping += self.config.sections["transfers"]["buddyshared"]

        if self.config.sections["transfers"]["sharedownloaddir"]:
            mapping += [(_("Downloaded"), self.config.sections["transfers"]["downloaddir"])]

        return mapping

    def convert_shares(self):
        """ Convert fs-based shared to virtual shared (pre 1.4.0) """

        def _convert_to_virtual(x):
            if isinstance(x, tuple):
                return x
            virtual = x.replace('/', '_').replace('\\', '_').strip('_')
            log.add("Renaming shared folder '%s' to '%s'. A rescan of your share is required." % (x, virtual))
            return (virtual, x)

        self.config.sections["transfers"]["shared"] = [_convert_to_virtual(x) for x in self.config.sections["transfers"]["shared"]]
        self.config.sections["transfers"]["buddyshared"] = [_convert_to_virtual(x) for x in self.config.sections["transfers"]["buddyshared"]]

    def load_shares(self, dbs):

        errors = []

        for destination, shelvefile in dbs:
            try:
                self.config.sections["transfers"][destination] = shelve.open(shelvefile, protocol=pickle.HIGHEST_PROTOCOL)
            except Exception:
                errors.append(shelvefile)

        if errors:
            log.add_warning(_("Failed to process the following databases: %(names)s") % {'names': '\n'.join(errors)})

            self.clear_shares()

            log.add_warning(_("Shared files database seems to be corrupted, rescan your shares"))

    def set_shares(self, sharestype="normal", files=None, streams=None, mtimes=None, wordindex=None, fileindex=None):

        if sharestype == "normal":
            storable_objects = [
                (files, "sharedfiles", "files.db"),
                (streams, "sharedfilesstreams", "streams.db"),
                (mtimes, "sharedmtimes", "mtimes.db"),
                (wordindex, "wordindex", "wordindex.db"),
                (fileindex, "fileindex", "fileindex.db")
            ]
        else:
            storable_objects = [
                (files, "bsharedfiles", "buddyfiles.db"),
                (streams, "bsharedfilesstreams", "buddystreams.db"),
                (mtimes, "bsharedmtimes", "buddymtimes.db"),
                (wordindex, "bwordindex", "buddywordindex.db"),
                (fileindex, "bfileindex", "buddyfileindex.db")
            ]

        for source, destination, filename in storable_objects:
            if source is not None:
                try:
                    self.config.sections["transfers"][destination].close()
                    self.config.sections["transfers"][destination] = shelve.open(os.path.join(self.config.data_dir, filename), flag='n', protocol=pickle.HIGHEST_PROTOCOL)
                    self.config.sections["transfers"][destination].update(source)

                except Exception as e:
                    log.add_warning(_("Can't save %s: %s") % (filename, e))
                    return

    def clear_shares(self):

        self.set_shares(sharestype="normal", files={}, streams={}, mtimes={}, wordindex={}, fileindex={})
        self.set_shares(sharestype="buddy", files={}, streams={}, mtimes={}, wordindex={}, fileindex={})

    def compress_shares(self, sharestype):

        if sharestype == "normal":
            streams = self.config.sections["transfers"]["sharedfilesstreams"]
        elif sharestype == "buddy":
            streams = self.config.sections["transfers"]["bsharedfilesstreams"]

        if streams is None:
            log.add_warning(_("ERROR: No %(type)s shares database available") % {"type": sharestype})
            return

        m = slskmessages.SharedFileList(None, streams)
        _thread.start_new_thread(m.make_network_message, (0, True))

        if sharestype == "normal":
            self.compressed_shares_normal = m
        elif sharestype == "buddy":
            self.compressed_shares_buddy = m

    def close_shares(self):
        for db in [
            "sharedfiles", "sharedfilesstreams", "wordindex",
            "fileindex", "sharedmtimes",
            "bsharedfiles", "bsharedfilesstreams", "bwordindex",
            "bfileindex", "bsharedmtimes"
        ]:
            self.config.sections["transfers"][db].close()

    def send_num_shared_folders_files(self):
        """
        Send number of files in buddy shares if only buddies can
        download, and buddy-shares are enabled.
        """

        config = self.config.sections

        if config["transfers"]["enablebuddyshares"] and config["transfers"]["friendsonly"]:
            shared_db = "bsharedfiles"
            index_db = "bfileindex"
        else:
            shared_db = "sharedfiles"
            index_db = "fileindex"

        try:
            sharedfolders = len(config["transfers"][shared_db])
            sharedfiles = len(config["transfers"][index_db])

        except TypeError:
            sharedfolders = len(list(config["transfers"][shared_db]))
            sharedfiles = len(list(config["transfers"][index_db]))

        self.queue.put(slskmessages.SharedFoldersFiles(sharedfolders, sharedfiles))

    """ Scanning """

    def rebuild_shares(self):
        self._rescan_shares("normal", rebuild=True)

    def rescan_shares(self, rebuild=False):
        self._rescan_shares("normal", rebuild)

    def rebuild_buddy_shares(self):
        self._rescan_shares("buddy", rebuild=True)

    def rescan_buddy_shares(self, rebuild=False):
        self._rescan_shares("buddy", rebuild)

    def _rescan_shares(self, sharestype, rebuild=False):

        if sharestype == "normal":
            log.add(_("Rescanning normal shares..."))

            mtimes = self.config.sections["transfers"]["sharedmtimes"]
            files = self.config.sections["transfers"]["sharedfiles"]
            filesstreams = self.config.sections["transfers"]["sharedfilesstreams"]

            shared_folders = self.config.sections["transfers"]["shared"][:]

            if self.config.sections["transfers"]["sharedownloaddir"]:
                shared_folders.append((_('Downloaded'), self.config.sections["transfers"]["downloaddir"]))

        else:
            log.add(_("Rescanning buddy shares..."))

            mtimes = self.config.sections["transfers"]["bsharedmtimes"]
            files = self.config.sections["transfers"]["bsharedfiles"]
            filesstreams = self.config.sections["transfers"]["bsharedfilesstreams"]

            shared_folders = self.config.sections["transfers"]["buddyshared"][:] + self.config.sections["transfers"]["shared"][:]

            if self.config.sections["transfers"]["sharedownloaddir"]:
                shared_folders.append((_('Downloaded'), self.config.sections["transfers"]["downloaddir"]))

        try:
            if self.ui_callback:
                self.ui_callback.set_scan_progress(sharestype, 0.0)
                self.ui_callback.show_scan_progress(sharestype)

            self.rescan_dirs(
                sharestype,
                shared_folders,
                mtimes,
                files,
                filesstreams,
                rebuild=rebuild
            )

            if self.ui_callback:
                self.ui_callback.rescan_finished(sharestype)

            self.compress_shares(sharestype)
            self.send_num_shared_folders_files()

        except Exception as ex:
            log.add(
                _("Failed to rebuild share, serious error occurred. If this problem persists delete %s/*.db and try again. If that doesn't help please file a bug report with the stack trace included (see terminal output after this message). Technical details: %s"), (self.config.data_dir, ex)
            )
            if self.ui_callback:
                self.ui_callback.hide_scan_progress(sharestype)

            raise

    def rescan_dirs(self, sharestype, shared, oldmtimes, oldfiles, oldstreams, rebuild=False):
        """
        Check for modified or new files via OS's last mtime on a directory,
        or, if rebuild is True, all directories
        """

        # returns dict in format:  { Directory : mtime, ... }
        shared_directories = (x[1] for x in shared)

        try:
            num_folders = len(oldmtimes)
        except TypeError:
            num_folders = len(list(oldmtimes))

        log.add(_("%(num)s folders found before rescan, rebuilding..."), {"num": num_folders})

        newmtimes = {}

        for folder in shared_directories:
            if not self.is_hidden(folder):
                # Get mtimes for top-level shared folders, then every subfolder
                mtime = os.stat(folder).st_mtime
                newmtimes[folder] = mtime
                newmtimes = {**newmtimes, **self.get_folder_mtimes(folder)}

        # Get list of files
        # returns dict in format { Directory : { File : metadata, ... }, ... }
        # returns dict in format { Directory : hex string of files+metadata, ... }
        newsharedfiles, newsharedfilesstreams = self.get_files_list(sharestype, newmtimes, oldmtimes, oldfiles, oldstreams, rebuild)

        # Save data to shelves
        self.set_shares(sharestype=sharestype, files=newsharedfiles, streams=newsharedfilesstreams, mtimes=newmtimes)

        # Update Search Index
        # wordindex is a dict in format {word: [num, num, ..], ... } with num matching keys in newfileindex
        # fileindex is a dict in format { num: (path, size, (bitrate, vbr), length), ... }
        self.get_files_index(sharestype, newsharedfiles)

        log.add(_("%(num)s folders found after rescan"), {"num": len(newsharedfiles)})

    def is_hidden(self, folder, filename=None, folder_obj=None):
        """ Stop sharing any dot/hidden directories/files """

        # If any part of the directory structure start with a dot we exclude it
        if filename is None:
            subfolders = folder.replace('\\', os.sep).split(os.sep)

            for part in subfolders:
                if part.startswith("."):
                    return True

        # If we're asked to check a file we exclude it if it start with a dot
        if filename is not None and filename.startswith("."):
            return True

        # Check if file is marked as hidden on Windows
        if sys.platform == "win32":
            if filename is not None:
                folder += '\\' + filename

            elif folder_obj is not None:
                # Faster way if we use scandir
                return folder_obj.stat().st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN

            return os.stat(folder).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN

        return False

    def add_file_to_index(self, index, filename, folder, fileinfo, wordindex, fileindex):
        """ Add a file to the file index database """

        fileindex[repr(index)] = (folder + '\\' + filename, *fileinfo[1:])

        # Collect words from filenames for Search index
        # Use set to prevent duplicates
        for k in set((folder + " " + filename).lower().translate(self.translatepunctuation).split()):
            try:
                wordindex[k].append(index)
            except KeyError:
                wordindex[k] = [index]

    def add_file_to_shared(self, name):
        """ Add a file to the normal shares database """

        config = self.config.sections
        if not config["transfers"]["sharedownloaddir"]:
            return

        shared = config["transfers"]["sharedfiles"]
        sharedstreams = config["transfers"]["sharedfilesstreams"]
        wordindex = config["transfers"]["wordindex"]
        fileindex = config["transfers"]["fileindex"]

        shareddirs = [path for _name, path in config["transfers"]["shared"]]
        shareddirs.append(config["transfers"]["downloaddir"])

        sharedmtimes = config["transfers"]["sharedmtimes"]

        rdir = str(os.path.expanduser(os.path.dirname(name)))
        vdir = self.real2virtual(rdir)
        file = str(os.path.basename(name))

        shared[vdir] = shared.get(vdir, [])

        if file not in [i[0] for i in shared[vdir]]:
            fileinfo = self.get_file_info(file, name)
            shared[vdir] += [fileinfo]

            sharedstreams[vdir] = self.get_dir_stream(shared[vdir])

            try:
                index = len(fileindex)
            except TypeError:
                index = len(list(fileindex))

            self.add_file_to_index(index, file, vdir, fileinfo, wordindex, fileindex)

            sharedmtimes[vdir] = os.path.getmtime(rdir)
            self.newnormalshares = True

        if config["transfers"]["enablebuddyshares"]:
            self.add_file_to_buddy_shared(name)

    def add_file_to_buddy_shared(self, name):
        """ Add a file to the buddy shares database """

        config = self.config.sections
        if not config["transfers"]["sharedownloaddir"]:
            return

        bshared = config["transfers"]["bsharedfiles"]
        bsharedstreams = config["transfers"]["bsharedfilesstreams"]
        bwordindex = config["transfers"]["bwordindex"]
        bfileindex = config["transfers"]["bfileindex"]

        bshareddirs = [path for _name, path in config["transfers"]["shared"]]
        bshareddirs += [path for _name, path in config["transfers"]["buddyshared"]]
        bshareddirs.append(config["transfers"]["downloaddir"])

        bsharedmtimes = config["transfers"]["bsharedmtimes"]

        rdir = str(os.path.expanduser(os.path.dirname(name)))
        vdir = self.real2virtual(rdir)
        file = str(os.path.basename(name))

        bshared[vdir] = bshared.get(vdir, [])

        if file not in [i[0] for i in bshared[vdir]]:

            fileinfo = self.get_file_info(file, name)
            bshared[vdir] += [fileinfo]

            bsharedstreams[vdir] = self.get_dir_stream(bshared[vdir])

            try:
                index = len(bfileindex)
            except TypeError:
                index = len(list(bfileindex))

            self.add_file_to_index(index, file, vdir, fileinfo, bwordindex, bfileindex)

            bsharedmtimes[vdir] = os.path.getmtime(rdir)
            self.newbuddyshares = True

    def get_folder_mtimes(self, folder):
        """ Get Modification Times """

        mtimes = {}

        try:
            for entry in os.scandir(folder):
                if entry.is_dir():

                    path = entry.path

                    if self.is_hidden(path):
                        return mtimes

                    try:
                        mtime = entry.stat().st_mtime
                    except OSError as errtuple:
                        log.add(_("Error while scanning %(path)s: %(error)s"), {
                            'path': path,
                            'error': errtuple
                        })
                        return mtimes

                    mtimes[path] = mtime
                    dircontents = self.get_folder_mtimes(path)

                    for k in dircontents:
                        mtimes[k] = dircontents[k]

        except OSError as errtuple:
            log.add(_("Error while scanning folder %(path)s: %(error)s"), {'path': folder, 'error': errtuple})

        return mtimes

    def get_files_list(self, sharestype, mtimes, oldmtimes, oldfiles, oldstreams, rebuild=False):
        """ Get a list of files with their filelength, bitrate and track length in seconds """

        files = {}
        streams = {}
        count = 0
        lastpercent = 0.0

        for folder in mtimes:

            try:
                count += 1

                if self.ui_callback:
                    # Truncate the percentage to two decimal places to avoid sending data to the GUI thread too often
                    percent = float("%.2f" % (float(count) / len(mtimes) * 0.75))

                    if percent > lastpercent and percent <= 1.0:
                        self.ui_callback.set_scan_progress(sharestype, percent)
                        lastpercent = percent

                virtualdir = self.real2virtual(folder)

                if not rebuild and folder in oldmtimes:
                    if mtimes[folder] == oldmtimes[folder]:
                        if os.path.exists(folder):
                            try:
                                files[virtualdir] = oldfiles[virtualdir]
                                streams[virtualdir] = oldstreams[virtualdir]
                                continue
                            except KeyError:
                                log.add_debug(_("Inconsistent cache for '%(vdir)s', rebuilding '%(dir)s'"), {
                                    'vdir': virtualdir,
                                    'dir': folder
                                })
                        else:
                            log.add_debug(_("Dropping missing folder %(dir)s"), {'dir': folder})
                            continue

                files[virtualdir] = []

                for entry in os.scandir(folder):

                    if entry.is_file():
                        filename = entry.name

                        if self.is_hidden(folder, filename):
                            continue

                        # Get the metadata of the file
                        data = self.get_file_info(filename, entry.path, entry)
                        if data is not None:
                            files[virtualdir].append(data)

                streams[virtualdir] = self.get_dir_stream(files[virtualdir])

            except OSError as errtuple:
                log.add(_("Error while scanning folder %(path)s: %(error)s"), {'path': folder, 'error': errtuple})
                continue

        return files, streams

    def get_file_info(self, name, pathname, file=None):
        """ Get metadata via taglib """

        try:
            audio = None

            if file:
                # Faster way if we use scandir
                size = file.stat().st_size
            else:
                size = os.stat(pathname).st_size

            if size > 0:
                try:
                    audio = taglib.File(pathname)
                except IOError:
                    pass

            if audio is not None:
                bitrateinfo = (int(audio.bitrate), int(False))  # Second argument used to be VBR (variable bitrate)
                fileinfo = (name, size, bitrateinfo, int(audio.length))
            else:
                fileinfo = (name, size, None, None)

            return fileinfo

        except Exception as errtuple:
            log.add(_("Error while scanning file %(path)s: %(error)s"), {'path': pathname, 'error': errtuple})

    def get_dir_stream(self, folder):
        """ Pack all files and metadata in directory """

        message = slskmessages.SlskMessage()
        stream = bytearray()
        stream.extend(message.pack_object(len(folder), unsignedint=True))

        for fileinfo in folder:
            stream.extend(bytes([1]))
            stream.extend(message.pack_object(fileinfo[0]))
            stream.extend(message.pack_object(fileinfo[1], unsignedlonglong=True))

            if fileinfo[2] is not None:
                try:
                    stream.extend(message.pack_object('mp3'))
                    stream.extend(message.pack_object(3))

                    stream.extend(message.pack_object(0))
                    stream.extend(message.pack_object(fileinfo[2][0], unsignedint=True))
                    stream.extend(message.pack_object(1))
                    stream.extend(message.pack_object(fileinfo[3], unsignedint=True))
                    stream.extend(message.pack_object(2))
                    stream.extend(message.pack_object(fileinfo[2][1]))
                except Exception:
                    log.add(_("Found meta data that couldn't be encoded, possible corrupt file: '%(file)s' has a bitrate of %(bitrate)s kbs, a length of %(length)s seconds and a VBR of %(vbr)s"), {
                        'file': fileinfo[0],
                        'bitrate': fileinfo[2][0],
                        'length': fileinfo[3],
                        'vbr': fileinfo[2][1]
                    })
                    stream.extend(message.pack_object(''))
                    stream.extend(message.pack_object(0))
            else:
                stream.extend(message.pack_object(''))
                stream.extend(message.pack_object(0))

        return stream

    def get_files_index(self, sharestype, sharedfiles):
        """ Update Search index with new files """

        """ We dump data directly into the file index shelf to save memory """
        if sharestype == "normal":
            section = target = "fileindex"
        else:
            section = "bfileindex"
            target = "buddyfileindex"

        self.config.sections["transfers"][section].close()

        fileindex = self.config.sections["transfers"][section] = \
            shelve.open(os.path.join(self.config.data_dir, target + ".db"), flag='n', protocol=pickle.HIGHEST_PROTOCOL)

        """ For the word index, we can't use the same approach as above, as we need
        to access dict elements frequently. This would take too long on a shelf. """
        wordindex = {}

        index = 0
        count = len(sharedfiles)
        lastpercent = 0.0

        for folder in sharedfiles:
            count += 1

            if self.ui_callback:
                # Truncate the percentage to two decimal places to avoid sending data to the GUI thread too often
                percent = float("%.2f" % (float(count) / len(sharedfiles) * 0.75))

                if percent > lastpercent and percent <= 1.0:
                    self.ui_callback.set_scan_progress(sharestype, percent)
                    lastpercent = percent

            for fileinfo in sharedfiles[folder]:
                self.add_file_to_index(index, fileinfo[0], folder, fileinfo, wordindex, fileindex)
                index += 1

        self.set_shares(sharestype=sharestype, wordindex=wordindex)

    """ Search request processing """

    def create_search_result_list(self, searchterm, wordindex, maxresults=50):

        try:
            """ Stage 1: Check if each word in the search term is included in our word index.
            If this is the case, we select the word that has the most file matches in our
            word index. If not, exit, since we don't have relevant results. """

            largest = 0

            for i in re.finditer(r'\S+', searchterm):
                i = i.group(0)

                if i not in wordindex:
                    return

                list_size = len(wordindex[i])

                if list_size > largest:
                    largest = list_size
                    largest_key = i

            """ Stage 2: Start with the word that has the most file matches, which we selected
            in the previous step, and gradually remove matches that other words in the search
            term don't have. Return the remaining matches, if any. """

            results = wordindex[largest_key]
            searchterm.replace(largest_key, '')

            for i in re.finditer(r'\S+', searchterm):
                results = set(results).intersection(wordindex[i.group(0)])

            return results

        except ValueError:
            # DB is closed, perhaps when rescanning share or closing Nicotine+
            return

    def process_search_request(self, searchterm, user, searchid, direct=0):
        """ Note: since this section is accessed every time a search request arrives,
        several times a second, please keep it as optimized and memory
        sparse as possible! """

        if not self.config.sections["searches"]["search_results"]:
            # Don't return _any_ results when this option is disabled
            return

        if searchterm is None:
            return

        if user == self.config.sections["server"]["login"]:
            # We shouldn't send a search response if we initiated the search request
            return

        maxresults = self.config.sections["searches"]["maxresults"]

        if maxresults == 0:
            return

        # Don't count excluded words as matches (words starting with -)
        # Strip punctuation
        searchterm = re.sub(r'(\s)-\w+', r'\1', searchterm).lower().translate(self.translatepunctuation).strip()

        if len(searchterm) < self.config.sections["searches"]["min_search_chars"]:
            # Don't send search response if search term contains too few characters
            return

        checkuser, reason = self.np.check_user(user, None)

        if not checkuser:
            return

        if checkuser == 2:
            wordindex = self.config.sections["transfers"]["bwordindex"]
        else:
            wordindex = self.config.sections["transfers"]["wordindex"]

        # Find common file matches for each word in search term
        resultlist = self.create_search_result_list(searchterm, wordindex, maxresults)

        if not resultlist:
            return

        if self.np.transfers is not None:

            numresults = min(len(resultlist), maxresults)
            queuesizes = self.np.transfers.get_upload_queue_sizes()
            slotsavail = self.np.transfers.allow_new_uploads()

            if reason == "geoip":
                geoip = 1
            else:
                geoip = 0

            if checkuser == 2:
                fileindex = self.config.sections["transfers"]["bfileindex"]
            else:
                fileindex = self.config.sections["transfers"]["fileindex"]

            fifoqueue = self.config.sections["transfers"]["fifoqueue"]

            message = slskmessages.FileSearchResult(
                None,
                self.config.sections["server"]["login"],
                geoip, searchid, resultlist, fileindex, slotsavail,
                self.np.speed, queuesizes, fifoqueue, numresults
            )

            self.np.process_request_to_peer(user, message)

            if direct:
                log.add_search(
                    _("User %(user)s is directly searching for \"%(query)s\", returning %(num)i results"), {
                        'user': user,
                        'query': searchterm,
                        'num': numresults
                    })
            else:
                log.add_search(
                    _("User %(user)s is searching for \"%(query)s\", returning %(num)i results"), {
                        'user': user,
                        'query': searchterm,
                        'num': numresults
                    })
