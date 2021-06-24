'''
    Prelude of common includes for whole project
'''

from copy import copy
from dataclasses import dataclass, field as dataclassfield
import enum
from enum import Enum, auto as enumerator
import logging
import os
from pathlib import Path
import re
import sys
from typing import (
    Any, BinaryIO, Callable, cast, ClassVar,
    Collection, Dict, Iterable, List, NewType, NoReturn,
    Optional, Set, Sized, TextIO, Tuple, Type, TypeVar, Union
)

def sourceDirectory(sourceFile: str) -> Path:
    return Path(os.path.dirname(os.path.abspath(sourceFile)))

class ClassMock:
    '''
        Special metastructure used in lazy initialization of dacaclasses or similar strucutres
        with required arguments.

        The key property is type having __dict__ and only trivial ctor/dtor
        Used pattern allows ergonomic `typing` based linting in IDEs and looks like following:
        ```
            resultPrototype: ResultType = cast(ResultType, ClassMock())
            resultPrototype.field = value
            # Now we can set any contents on this dummy value
            result: ResultType = ResultType(**resultPrototype.__dict__)
        ```
    '''
    pass
