'''
    Common includes for whole project
'''

from dataclasses import dataclass, field as dataclassfield
from enum import Enum
import logging
import os
from pathlib import Path
import re
import sys
from typing import (
    Any, BinaryIO, Callable, cast,
    Collection, Dict, List, NewType, NoReturn,
    Optional, Set, Sized, TextIO, Tuple, TypeVar, Union
)
