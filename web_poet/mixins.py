from urllib.parse import urljoin

import parsel
from w3lib.html import get_base_url


class ResponseShortcutsMixin:
    """Common shortcut methods for working with HTML responses.

    It requires "response" attribute to be present.
    """
    _cached_base_url = None

    @property
    def url(self):
        """Shortcut to HTML Response's URL."""
        return self.response.url

    @property
    def html(self):
        """Shortcut to HTML Response's content."""
        return self.response.text

    @property
    def selector(self) -> parsel.Selector:
        """``parsel.Selector`` instance for the HTML Response."""
        # TODO: when dropping Python 3.7 support,
        #  implement it using typing.Protocol
        return self.response.selector  # type: ignore

    def xpath(self, query, **kwargs):
        """Run an XPath query on a response, using :class:`parsel.Selector`."""
        return self.selector.xpath(query, **kwargs)

    def css(self, query):
        """Run a CSS query on a response, using :class:`parsel.Selector`."""
        return self.selector.css(query)

    @property
    def base_url(self) -> str:
        """Return the base url of the given response"""
        # FIXME: move it to HttpResponse
        if self._cached_base_url is None:
            text = self.html[:4096]
            self._cached_base_url = get_base_url(text, self.url)
        return self._cached_base_url

    def urljoin(self, url: str) -> str:
        """Convert url to absolute, taking in account
        url and baseurl of the response"""
        # FIXME: move it to HttpResponse
        return urljoin(self.base_url, url)
