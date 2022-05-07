"""
HTTP Exceptions
~~~~~~~~~~~~~~~

These are exceptions pertaining to common issues faced when executing HTTP
operations.
"""

from web_poet.page_inputs.http import HttpResponse, HttpRequest


class HttpError(IOError):
    """Indicates that an exception has occurred when handling an HTTP operation.

    This is used as a **base class** for more specific errors and could be vague
    since it could denote problems either in the HTTP Request or Response.

    For more specific errors, it would be better to use :class:`.HttpRequestError`
    and :class:`.HttpResponseError`.

    :param request: The :class:`~.HttpRequest` instance that was used.
    :type request: HttpRequest
    :param response: The :class:`~.HttpResponse` instance that was received, if
        any. Note that this wouldn't exist if the problem ocurred when executing
        the :class:`~.HttpRequest`.
    :type response: HttpResponse
    """

    def __init__(
        self,
        *args,
        request: HttpRequest = None,
        response: HttpResponse = None,
        **kwargs
    ):
        self.response = response
        self.request = request
        super().__init__(*args, **kwargs)


class HttpRequestError(HttpError):
    """Indicates that an exception has occurred when the **HTTP Request** was
    being handled.
    """

    pass


class HttpResponseError(HttpError):
    """Indicates that an exception has occurred when the **HTTP Response** was
    received.

    For responses that are in the status code ``100-3xx range``, this exception
    shouldn't be raised at all. However, for responses in the ``400-5xx``, this
    will be raised by **web-poet**.

    .. note::

        Frameworks implementing **web-poet** should **NOT** raise this themselves
        but rather, rely on the ``allow_status`` parameter found in the methods
        of :class:`~.HttpClient`.
    """

    pass
