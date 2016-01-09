
import os.path
import shutil
import subprocess
import uuid


class Torrent:
    """
    Represents a torrent for an Upload
    """

    def __init__(self, config, upload):
        """
        :param config: config dict (usually flask app.config)
        :param upload: upload model object
        :return:
        """
        self.torrents_dir = config.get('TORRENTS_DIR')
        self.torrents_data_dir = config.get('TORRENTS_DATA_DIR')
        self.upload = upload

    def exists(self):
        """
        :return: bool whether .torrent actually exists on disk
        """
        return os.path.exists(self.get_torrent_path())


    def get_torrent_path(self):
        """
        :return: str abs path to .torrent file, which may or may not actually exist
        """
        return os.path.join(self.torrents_dir, "%s.torrent" % (self.upload.structured_file_name,))

    def create(self):
        """
        Creates a .torrent file for the contained Upload object,
        and ensures the data file exists in a data directory.
        """

        # TODO: I tried creating a symlink from uploads, but transmission
        # uses the original filename (containing only title) when it creates
        # the .torrent file. This causes transmission to fail to seed from the
        # symlink, and will also eventually cause filename collisions.
        #
        # For this proof of concept, we duplicate the data and make a copy of the file.

        torrent_path = self.get_torrent_path()
        datafile_path = os.path.join(self.torrents_data_dir, self.upload.structured_file_name)

        if not os.path.exists(torrent_path):
            if os.path.exists(self.upload.full_path()):
                if os.path.exists(datafile_path):
                    raise Exception("Duplicate found: " + datafile_path)
                try:
                    print "trying to symlink from %s to %s" % (self.upload.full_path(), datafile_path)

                    # this won't work right: see note above
                    # os.symlink(upload.full_path(), datafile_path)

                    shutil.copy(self.upload.full_path(), datafile_path)
                except Exception, e:
                    raise Exception("Couldn't make symlink: %s" % (e,))

                # create as tmpfile and move it, otherwise transmission-daemon
                # tries to read the file too quickly and fails b/c of perms
                tmpfile = "/tmp/%s" % (uuid.uuid4())
                output = subprocess.check_output(["transmission-create", datafile_path, "-o", tmpfile],
                                                 stderr=subprocess.STDOUT)
                if os.path.exists(tmpfile):
                    os.chmod(tmpfile, 0664)
                    shutil.move(tmpfile, torrent_path)
                else:
                    raise Exception("Error running transmission to create torrent file: %s" % (output,))
            else:
                raise Exception("File doesn't exist for Upload object: %s" % (self.upload.full_path(),))

        return torrent_path

    def get_magnet_link(self):
        torrent_path = self.get_torrent_path()
        if os.path.exists(torrent_path):
            output = subprocess.check_output(["transmission-show", "-m", torrent_path], stderr=subprocess.STDOUT)
            return output.strip()
        return None
