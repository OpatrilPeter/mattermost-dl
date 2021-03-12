'''
    Common includes for whole project
'''

from copy import copy
from dataclasses import dataclass, field as dataclassfield
import enum
from enum import Enum
import logging
import os
from pathlib import Path
import re
import sys
from typing import (
    Any, BinaryIO, Callable, cast,
    Collection, Dict, Iterable, List, NewType, NoReturn,
    Optional, Set, Sized, TextIO, Tuple, Type, TypeVar, Union
)

def sourceDirectory(sourceFile: str) -> Path:
    return Path(os.path.dirname(os.path.abspath(sourceFile)))
