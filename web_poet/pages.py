import abc
import typing
from contextlib import suppress

import attr

from web_poet._typing import get_item_cls
from web_poet.fields import FieldsMixin, item_from_fields
from web_poet.mixins import ResponseShortcutsMixin
from web_poet.page_inputs import HttpResponse
from web_poet.utils import _create_deprecated_class, cached_method, validate_input


class Injectable(abc.ABC, FieldsMixin):
    """Base Page Object class, which all Page Objects should inherit from
    (probably through Injectable subclasses).

    Frameworks which are using ``web-poet`` Page Objects should use
    :func:`is_injectable` function to detect if an object is an Injectable,
    and if an object is injectable, allow building it automatically
    through dependency injection, using https://github.com/scrapinghub/andi
    library.

    Instead of inheriting you can also use ``Injectable.register(MyWebPage)``.
    ``Injectable.register`` can also be used as a decorator.
    """

    pass


# NoneType is considered as injectable. Required for Optionals to work.
Injectable.register(type(None))


def is_injectable(cls: typing.Any) -> bool:
    """Return True if ``cls`` is a class which inherits
    from :class:`~.Injectable`."""
    return isinstance(cls, type) and issubclass(cls, Injectable)


ItemT = typing.TypeVar("ItemT")


class Returns(typing.Generic[ItemT]):
    """Inherit from this generic mixin to change the item class used by
    :class:`~.ItemPage`"""

    @property
    def item_cls(self) -> typing.Type[ItemT]:
        """Item class"""
        return get_item_cls(self.__class__, default=dict)


_NOT_SET = object()


class ItemPage(Injectable, Returns[ItemT]):
    """Base Page Object, with a default :meth:`to_item` implementation
    which supports web-poet fields.
    """

    _skip_nonitem_fields = _NOT_SET

    def _get_skip_nonitem_fields(self) -> bool:
        value = self._skip_nonitem_fields
        return False if value is _NOT_SET else bool(value)

    def __init_subclass__(cls, skip_nonitem_fields=_NOT_SET, **kwargs):
        super().__init_subclass__(**kwargs)
        if skip_nonitem_fields is _NOT_SET:
            # This is a workaround for attrs issue.
            # See: https://github.com/scrapinghub/web-poet/issues/141
            return
        cls._skip_nonitem_fields = skip_nonitem_fields

    @validate_input
    async def to_item(self) -> ItemT:
        """Extract an item from a web page"""
        return await item_from_fields(
            self,
            item_cls=self.item_cls,
            skip_nonitem_fields=self._get_skip_nonitem_fields(),
        )

    @cached_method
    def _validate_input(self) -> None:
        """Run self.validate_input if defined."""
        if not hasattr(self, "validate_input"):
            return
        with suppress(AttributeError):
            if self.__validating_input:
                # We are in a recursive call, i.e. _validate_input is being
                # called from _validate_input itself (likely through a @field
                # method).
                return

        self.__validating_input: bool = True
        validation_item = self.validate_input()  # type: ignore[attr-defined]
        self.__validating_input = False
        return validation_item


@attr.s(auto_attribs=True)
class WebPage(ItemPage[ItemT], ResponseShortcutsMixin):
    """Base Page Object which requires :class:`~.HttpResponse`
    and provides XPath / CSS shortcuts.
    """

    response: HttpResponse


ItemWebPage = _create_deprecated_class("ItemWebPage", WebPage, warn_once=False)
