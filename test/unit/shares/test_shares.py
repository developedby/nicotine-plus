# COPYRIGHT (C) 2020 Nicotine+ Team
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
import queue

from pynicotine.shares import Shares
from pynicotine.config import Config

DB_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "dbs")
SHARES_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "sharedfiles")


def test_shares_scan():
    """ Test a full shares scan """

    config = Config("temp_config", DB_DIR)
    config.sections["transfers"]["shared"] = [("Shares", SHARES_DIR)]

    shares = Shares(None, config, queue.Queue(0))
    shares.rescan_shares()

    # Verify that modification time was saved for shares folder
    assert SHARES_DIR in list(config.sections["transfers"]["sharedmtimes"])

    # Verify that shared files were added
    assert ('dummy_file', 0, None, None) in list(config.sections["transfers"]["sharedfiles"].values())[0]
    assert ('nicotinetestdata.mp3', 80919, (128, 0), 5) in list(config.sections["transfers"]["sharedfiles"].values())[0]

    # Verify that search index was updated
    word_index = config.sections["transfers"]["wordindex"]
    nicotinetestdata_indexes = list(word_index["nicotinetestdata"])
    ogg_indexes = list(word_index["ogg"])

    assert set(word_index) == set(['nicotinetestdata', 'ogg', 'mp3', 'shares', 'file', 'dummy'])
    assert len(nicotinetestdata_indexes) == 2
    assert len(ogg_indexes) == 1

    # File ID associated with word "ogg" should return our nicotinetestdata.ogg file
    assert ogg_indexes[0] in nicotinetestdata_indexes
    assert config.sections["transfers"]["fileindex"][str(ogg_indexes[0])][0] == 'Shares\\nicotinetestdata.ogg'

    # Verify that dbs are cleared
    shares.clear_shares()
    assert len(list(config.sections["transfers"]["sharedfiles"])) == 0


def test_shares_add_downloaded():
    """ Test that downloaded files are added to shared files """

    config = Config("temp_config", DB_DIR)
    config.sections["transfers"]["shared"] = [("Downloaded", SHARES_DIR)]
    config.sections["transfers"]["sharedownloaddir"] = True

    shares = Shares(None, config, queue.Queue(0), None)
    shares.add_file_to_shared(os.path.join(SHARES_DIR, 'nicotinetestdata.mp3'))

    assert ('nicotinetestdata.mp3', 80919, (128, 0), 5) in list(config.sections["transfers"]["sharedfiles"].values())[0]
    assert ('Downloaded\\nicotinetestdata.mp3', 80919, (128, 0), 5) in config.sections["transfers"]["fileindex"].values()
