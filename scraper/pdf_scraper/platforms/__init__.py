"""
Platform detectors and handlers (extensible):
- mijnstembureau: portals like mijnstembureau-<slug>.nl or stembureau-<slug>.nl
- pleio: *.pleio.nl groups/files views
- google-drive: drive.google.com file/folder
- stackstorage: stackstorage.com public share
- mediafiler: *.mediafiler.net gallery/files

Generic discovery catches a lot of direct .pdf links; these handlers are for
specific platforms where targeted enumeration reduces requests.
"""

from typing import Optional, Callable, List, Dict


def detect(url: str) -> Optional[str]:
    u = (url or "").lower()
    if 'mijnstembureau' in u or 'stembureau-' in u:
        return 'mijnstembureau'
    if 'pleio.nl' in u:
        return 'pleio'
    if 'drive.google.com' in u:
        return 'google-drive'
    if 'stackstorage.com' in u:
        return 'stackstorage'
    if 'mediafiler' in u:
        return 'mediafiler'
    if 'sharepoint.com' in u or 'onedrive.live.com' in u or '1drv.ms' in u or '/_layouts/15/download.aspx' in u:
        return 'sharepoint'
    if 'ibabs' in u:
        return 'ibabs'
    if 'decosjoin' in u or 'decos' in u or 'dsresource' in u:
        return 'decos'
    return None


Handler = Callable[[str, object, object, str], List[Dict]]

REGISTRY: dict[str, Handler] = {}

def register(name: str, handler: Handler):
    REGISTRY[name] = handler

# Register built-ins
from .mijnstembureau import handle as _msb_handle
from .pleio import handle as _pleio_handle
from .drive import handle as _drive_handle
from .stack import handle as _stack_handle
from .mediafiler import handle as _mf_handle
from .sharepoint import handle as _sp_handle
from .ibabs import handle as _ibabs_handle
from .decos import handle as _decos_handle

register('mijnstembureau', _msb_handle)
register('pleio', _pleio_handle)
register('google-drive', _drive_handle)
register('stackstorage', _stack_handle)
register('mediafiler', _mf_handle)
register('sharepoint', _sp_handle)
register('ibabs', _ibabs_handle)
register('decos', _decos_handle)
