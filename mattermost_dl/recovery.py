'''
    Contains logic pertaining to arbitrage in situations
    where downloaded data may get lost.
'''

from .common import *

from .bo import Channel
from .config import ChannelOptions, ConfigFile
from .recovery_actions import RBackup, RDelete, RReuse, RSkipDownload
from .store import ChannelHeader

class RecoveryArbiter:
    '''
        Decision maker that centralises reasoning in all situations
        that may result in data loss.

        Acts as an interface that subclasses may use to, for example, ask user
        for decision interactively.
    '''
    def __init__(self, config: ConfigFile) -> None:
        self.config = config

    def onUnloadableHeader(self, channel: Channel, headerFilename: Path, dataFilename: Path) -> Union[RDelete, RBackup]:
        '''
            If header can't be loaded, should be backup the post storage, if it exists?
        '''
        if dataFilename.is_file():
            logging.info(f"Will back up posts in file '{dataFilename}', its respective channel header '{headerFilename}' couldn't be loaded.")
        return RBackup()

    def onMissizedDataFile(self, header: ChannelHeader, dataFilename: Path, size: Optional[int]
        ) -> Union[RBackup, RDelete, RReuse, RSkipDownload]:
        '''
            Invoked if data file for a header isn't found or its size doesn't match expectations.

            Size is actual computed filesize or None if file size couldn't be computed.

            @returns either
                - RBackup - corrupted archive is backuped up
                - RDelete - corrupted archive is removed
                - RReuse - allowed only if size is bigger than expected. Archive is truncated to expected size
                - RSkipDownload - aborts downloading given channel
        '''

        headerSize = header.storage.byteSize if header.storage is not None else 0

        if size is None:
            logging.warning(f"Failed to open file '{dataFilename}' containing posts for channel '{header.channel.internalName}'."
                + ' Channel data will be redownloaded, old header backed up.'
            )
        elif size < headerSize:
            logging.warning(
                f"Post storage for archive of channel '{header.channel.internalName}' has smaller size ({size}B) than expected ({headerSize}B)."
                + ' Channel data will be redownloaded, old header backed up.'
            )
        elif size > headerSize:
            logging.warning(
                f"Post storage for archive of channel '{header.channel.internalName}' is bigger ({size}B) than expected ({headerSize}B)."
                + ' This could be caused by previous interrupted (uncommited) download - if so, it can be fixed by reducing file to instructed size.'
                + ' Old archive will be backed up and channel redownloaded.'
            )
        return RBackup()

    def onArchiveReuse(self, header: ChannelHeader, options: ChannelOptions, reusable: bool) -> Union[RBackup, RDelete, RReuse, RSkipDownload]:
        '''
            Decides how to handle previous channel archive that was downloaded already should be appended into or downloaded from scratch altogether.

            @param reusable True if archive storage is viable for updating (appending)

            @returns either
                - RBackup - stores new file from scratch, backups previous
                - RReuse - if reusable, appends previous content, otherwise start new one from scratch, but keep previous in case of rollback
                - RDelete - stores new file from scratch, deletes previous
                - RSkipDownload - aborts downloading given channel
        '''
        if reusable:
            return options.onExistingCompatibleArchive
        else:
            if options.onExistingIncompatibleArchive == RDelete():
                return RReuse()
            else:
                return options.onExistingIncompatibleArchive

    def onPostLoadingFailure(self, header: ChannelHeader, headerFilename: Path, dataFilename: Path, err: BaseException) -> Union[RBackup, RDelete]:
        '''
            If post loading fails in the progress, should we remove the already downloaded files?

            @returns either
                - RBackup - keep temporarily downloaded state
                - RDelete - remove downloaded data
        '''
        logging.warning(f"Downloading of channel '{header.channel.internalName}' failed, partially downloaded content is left for inspection.\nReason: {err}")
        return RBackup()

    def onExistingChannelBackup(self, channel: Channel, headerFilename: Path, dataFilename: Path) -> Union[RBackup, RDelete, RSkipDownload]:
        '''
            Called if backup creation is requested and its primary backup already exists.

            @returns either
                - RBackup - old backup is retained under different name
                - RDelete - old backup is overriden
                - RSkipDownload - aborts downloading given channel
        '''
        logging.warning(
            f"Can't backup archive for '{channel.internalName}', as previous backup exist. Previous backup will be renamed."
        )
        return RBackup()
