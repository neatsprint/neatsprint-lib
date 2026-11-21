"""NeatSprint shared service library.

Public surface is intentionally small; import submodules explicitly:

    from neatsprint_lib.settings import ServiceSettings
    from neatsprint_lib.errors import ApiError
    from neatsprint_lib.api import create_health_router
"""

from neatsprint_lib.errors import ApiError
from neatsprint_lib.ids import new_id
from neatsprint_lib.settings import ServiceSettings

__all__ = ["ApiError", "ServiceSettings", "new_id"]
__version__ = "0.1.0"
