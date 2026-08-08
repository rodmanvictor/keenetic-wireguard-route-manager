"""Best-effort website icon URLs for the desktop domain list."""

from urllib.parse import urlencode

from keenetic_router.services.registry import normalize_domain


GOOGLE_FAVICON_ENDPOINT = 'https://www.google.com/s2/favicons'


def favicon_url(domain: str, size: int = 64) -> str:
    """Return a validated Google S2 favicon URL for one domain.

    Args:
        domain: Hostname already managed by the application.
        size: Requested square size from 16 through 256 pixels.

    Returns:
        HTTPS image URL suitable for a Flet ``Image`` or ``CircleAvatar``.

    Raises:
        ValueError: If the domain or requested size is invalid.

    Notes:
        Google does not publish a formal support contract for the S2 endpoint.
        The UI therefore always renders a local letter fallback when the image
        cannot be loaded.
    """
    canonical = normalize_domain(domain)
    if not 16 <= int(size) <= 256:
        raise ValueError('Размер favicon должен быть от 16 до 256 пикселей')
    query = urlencode({'domain': canonical, 'sz': int(size)})
    return f'{GOOGLE_FAVICON_ENDPOINT}?{query}'
