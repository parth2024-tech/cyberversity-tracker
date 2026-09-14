"""
Newspaper service subpackage: live fetching and document rendering.
"""

from ai_security_monitor.application.services.newspaper.fetcher import (
    NewspaperLiveFetcher,
)
from ai_security_monitor.application.services.newspaper.renderer import (
    NewspaperRenderer,
    NumberedCanvas,
)

__all__ = ["NewspaperLiveFetcher", "NewspaperRenderer", "NumberedCanvas"]
