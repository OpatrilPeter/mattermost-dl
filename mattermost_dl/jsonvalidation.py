'''
    Contains helpers for validating JSON schemas of
    program's internal representation of data
'''

from .common import *

from jsonschema.validators import Draft7Validator
from jsonschema.exceptions import ValidationError

@dataclass
class BadObject:
    recieved: Type

    def __str__(self) -> str:
        return f"not of object JSON type (real python type {self.recieved})"

@dataclass
class UnsupportedVersion:
    required: str
    found: str

    def __str__(self) -> str:
        return f"expected version {self.required}, found {self.found}"

@dataclass
class InvalidVersion:
    found: Any

    def __str__(self) -> str:
        return f"unrecognized version {self.found} is not in expected format (a string matching /\\d+(\\.\\d+){0,2}/ regex)"

class MissingVersion:
    def __str__(self) -> str:
        return "missing versioning information, it may not be loadable and some data may be lost"

ValidationErrors = Union[
    BadObject,
    Iterable[ValidationError],
]

ValidationWarnings = Union[
    MissingVersion,
    UnsupportedVersion,
    InvalidVersion,
]

def formatValidationErrors(errors: Iterable[ValidationError]) -> str:
    errorMessage = 'List of errors follows:\n'
    for error in errors:
        errorMessage += f'  error: {error.message} at #/{"/".join(error.absolute_path)}\n'
        errorMessage += f'    invalid part: {error.instance}\n'
    return errorMessage

def validate(jsonObject: Any, validator: Draft7Validator,
        # currently can only contains the delimiting major version
        acceptedVersion: Optional[str], # None means no versioning check
        onWarning: Callable[[ValidationWarnings], None],
        onError: Callable[[ValidationErrors], NoReturn]
    ) -> dict:
    '''
        Loads (potentially) versioned JSON representation of some Store entity
    '''
    if not isinstance(jsonObject, dict):
        onError(BadObject(type(jsonObject)))
    if acceptedVersion is not None:
        if 'version' not in jsonObject:
            onWarning(MissingVersion())
        elif not isinstance(jsonObject['version'], str) or not re.match(r'^\d+(\.\d+(\.\d+)?.*)?', jsonObject['version']):
            onWarning(InvalidVersion(jsonObject['version']))
        else:
            version = jsonObject['version']
            if not re.match(fr'^{acceptedVersion}\.?.*', version):
                onWarning(UnsupportedVersion(required="0", found=version))

    # This actually performs the validation
    validationErrors = [error for error in validator.iter_errors(jsonObject)]
    if len(validationErrors) > 0:
        onError(validationErrors)
    return jsonObject
