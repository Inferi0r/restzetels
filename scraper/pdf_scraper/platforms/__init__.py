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
    # Only treat as mijnstembureau when the host matches, not just any path
    try:
        from urllib.parse import urlparse as _up
        host = _up(url).netloc.lower()
    except Exception:
        host = ''
    if ('mijnstembureau' in host) or host.startswith('stembureau-'):
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
    # Amsterdam PV overview/API
    if ('amsterdam.nl' in u and 'verkiezingen' in u and ('overzicht-proces-verbalen' in u or 'processen-verbaal' in u)) or ('api.data.amsterdam.nl' in u) or ('pv-verkiezingen.amsterdam.nl' in u):
        return 'amsterdam-pv'
    # Municipal election subdomain portals (e.g., verkiezingen.sudwestfryslan.nl)
    try:
        from urllib.parse import urlparse as _up
        host = _up(url).netloc.lower()
        if host.startswith('verkiezingen.'):
            return 'verkiezingen-portal'
    except Exception:
        pass
    return None


Handler = Callable[[str, object, object, str], List[Dict]]

REGISTRY: dict[str, Handler] = {}

def register(name: str, handler: Handler):
    REGISTRY[name] = handler

# Register built-ins
try:
    from .mijnstembureau import handle as _msb_handle
    register('mijnstembureau', _msb_handle)
except Exception:
    # Platform optional; do not block others on import issues
    pass
from .pleio import handle as _pleio_handle
from .drive import handle as _drive_handle
from .stack import handle as _stack_handle
from .mediafiler import handle as _mf_handle
from .sharepoint import handle as _sp_handle
from .ibabs import handle as _ibabs_handle
from .decos import handle as _decos_handle
from .verkiezingen_portal import handle as _vz_handle
from .amsterdam import handle as _ams_handle

register('pleio', _pleio_handle)
register('google-drive', _drive_handle)
register('stackstorage', _stack_handle)
register('mediafiler', _mf_handle)
register('sharepoint', _sp_handle)
register('ibabs', _ibabs_handle)
register('decos', _decos_handle)
register('verkiezingen-portal', _vz_handle)
register('amsterdam-pv', _ams_handle)
