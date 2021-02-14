'''
    Helper utilities to visualise progress in long running foreground tasks,
    working in interactive and noninteractive environment.
'''

from common import *

from copy import copy

class VisualizationMode(Enum):
    DumbTerminal = 0
    AnsiEscapes = 1

@dataclass
class ProgressSettings:
    mode: VisualizationMode = VisualizationMode.AnsiEscapes
    forceMode: bool = False

class ProgressReporter:
    def __init__(self, io: TextIO, settings: ProgressSettings = ProgressSettings(), header: str = '', footer: str = '', contentPadding: int = 0, contentAlignLeft: bool = True):
        self.io: TextIO = io
        self.settings: ProgressSettings = copy(settings)
        self.header: str = header
        self.contentPadding: int = contentPadding
        self.contentAlignLeft: bool = contentAlignLeft
        self.footer: str = footer

        if not settings.forceMode:
            if not self.io.isatty():
                self.settings.mode = VisualizationMode.DumbTerminal
    def open(self):
        if self.settings.mode == VisualizationMode.AnsiEscapes:
            self.io.write(self.header+'\x1b[s')
            self.io.flush()
    def update(self, content: str, redraw: bool = False):
        padding = max(self.contentPadding-len(content), 0)
        if padding:
            if self.contentAlignLeft:
                paddedContent = content + ' '*padding
            else:
                paddedContent = ' '*padding + content
        else:
            paddedContent = content
        if self.settings.mode == VisualizationMode.DumbTerminal:
            self.io.write(self.header+paddedContent+self.footer+'\n')
        elif self.settings.mode == VisualizationMode.AnsiEscapes:
            if redraw:
                self.open()
            self.io.write('\x1b[u'+paddedContent+self.footer+'\x1b[0K')
            self.io.flush()
    def close(self):
        if self.settings.mode == VisualizationMode.AnsiEscapes:
            # Move to start of new line
            self.io.write('\n')
            self.io.flush()

class ProgressBar:
    '''
        Draws a bar that (possibly interactively) fills up to given value.
    '''
    def __new__(cls, io: TextIO, upto: int = 100, charSize: int = 10, settings: ProgressSettings = ProgressSettings()) -> 'ProgressBar':
        if not io.isatty() and not settings.forceMode:
            obj = super().__new__(_DumbProgressBar)
        else:
            obj = super().__new__(cls)
        return obj

    def __init__(self, io: TextIO, upto: int, charSize: int, settings: ProgressSettings = ProgressSettings()):
        self.reporter: ProgressReporter = ProgressReporter(io=io, settings=settings, header='[', footer=']', contentPadding=charSize)
        # Display size
        self.charSize: int = charSize
        self.upto: int = upto
    def open(self):
        self.reporter.open()
    def update(self, value: int, upto: int = None):
        upto = self.upto if upto is None else upto
        assert value >= 0 and value <= upto
        filledChars = value * self.charSize // upto
        self.reporter.update('.'*filledChars + ' '*(self.charSize-filledChars))
    def close(self):
        self.reporter.close()

class _DumbProgressBar(ProgressBar):
    def __init__(self, io: TextIO, upto: int, charSize: int, *args, **kwargs):
        self.io: TextIO = io
        self.charSize: int = charSize
    def open(self):
        pass
    def update(self, *args, **kwargs):
        pass
    def close(self):
        self.io.write(f'[{"."*self.charSize}]')

if __name__ == '__main__':
    import sys
    from time import sleep

    print("Progress test starts...")
    report = ProgressReporter(sys.stdout, header='Progress: ', footer= ' files')
    report.open()
    for i in range(100):
        report.update(f'{i+1}/100')
        sleep(0.01)
    report.close()
    print("Progress test ends...")

    print("Loading bar: ", end='')
    bar = ProgressBar(sys.stdout, upto=100, charSize=16)
    bar.open()
    for i in range(101):
        bar.update(i)
        sleep(0.05)
    bar.close()
    print()
