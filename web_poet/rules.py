from __future__ import annotations  # https://www.python.org/dev/peps/pep-0563/

import importlib
import importlib.util
import pkgutil
import warnings
from collections import defaultdict, deque
from operator import attrgetter
from typing import (
    Any,
    DefaultDict,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Type,
    TypeVar,
    Union,
)

import attrs
from url_matcher import Patterns, URLMatcher

from web_poet._typing import get_item_cls
from web_poet.page_inputs.url import _Url
from web_poet.pages import ItemPage
from web_poet.utils import _create_deprecated_class, as_list, str_to_pattern

Strings = Union[str, Iterable[str]]

RulesRegistryTV = TypeVar("RulesRegistryTV", bound="RulesRegistry")


@attrs.define(frozen=True)
class ApplyRule:
    """A rule that primarily applies Page Object and Item overrides for a given
    URL pattern.

    This is instantiated when using the :func:`web_poet.handle_urls` decorator.
    It's also being returned as a ``List[ApplyRule]`` when calling the
    ``web_poet.default_registry``'s :meth:`~.RulesRegistry.get_rules`
    method.

    You can access any of its attributes:

        * ``for_patterns`` - contains the list of URL patterns associated with
          this rule. You can read the API documentation of the `url-matcher
          <https://url-matcher.readthedocs.io/>`_ package for more information
          about the patterns.
        * ``use`` - The Page Object that will be **used** in cases where the URL
          pattern represented by the ``for_patterns`` attribute is matched.
        * ``instead_of`` - *(optional)* The Page Object that will be **replaced**
          with the Page Object specified via the ``use`` parameter.
        * ``to_return`` - *(optional)* The item class that the Page Object specified
          in ``use`` is capable of returning.
        * ``meta`` - *(optional)* Any other information you may want to store.
          This doesn't do anything for now but may be useful for future API updates.

    The main functionality of this class lies in the ``instead_of`` and ``to_return``
    parameters. Should both of these be omitted, then :class:`~.ApplyRule` simply
    tags which URL patterns the given Page Object defined in ``use`` is expected
    to be used on.

    When ``to_return`` is not None (e.g. ``to_return=MyItem``),
    the Page Object in ``use`` is declared as capable of returning a certain
    item class (i.e. ``MyItem``).

    When ``instead_of`` is not None (e.g. ``instead_of=ReplacedPageObject``),
    the rule adds an expectation that the ``ReplacedPageObject`` wouldn't
    be used for the URLs matching ``for_patterns``, since the Page Object
    in ``use`` will replace it.

    If there are multiple rules which match a certain URL, the rule
    to apply is picked based on the priorities set in ``for_patterns``.

    More information regarding its usage in :ref:`rules-intro`.

    .. tip::

        The :class:`~.ApplyRule` is also hashable. This makes it easy to store
        unique rules and identify any duplicates.
    """

    for_patterns: Patterns = attrs.field(converter=str_to_pattern)
    use: Type[ItemPage] = attrs.field(kw_only=True)
    instead_of: Optional[Type[ItemPage]] = attrs.field(default=None, kw_only=True)
    to_return: Optional[Type[Any]] = attrs.field(default=None, kw_only=True)
    meta: Dict[str, Any] = attrs.field(factory=dict, kw_only=True)

    def __hash__(self):
        return hash((self.for_patterns, self.use, self.instead_of, self.to_return))


class RulesRegistry:
    """
    RulesRegistry provides features for storing, retrieving,
    and searching for the :class:`~.ApplyRule` instances.

    ``web-poet`` provides a default Registry named ``default_registry``
    for convenience. It can be accessed this way:

    .. code-block:: python

        from web_poet import handle_urls, default_registry, WebPage
        from my_items import Product

        @handle_urls("example.com")
        class ExampleComProductPage(WebPage[Product]):
            ...

        rules = default_registry.get_rules()

    The ``@handle_urls`` decorator exposed as ``web_poet.handle_urls`` is a
    shortcut for ``default_registry.handle_urls``.

    .. note::

        It is encouraged to use the ``web_poet.default_registry`` instead of
        creating your own :class:`~.RulesRegistry` instance. Using multiple
        registries would be unwieldy in most cases (see :ref:`rules-custom-registry`).

        However, it might be applicable in certain scenarios like storing custom
        rules to separate it from the ``default_registry``. This :ref:`example
        <rules-custom-registry>` from the tutorial section may provide some
        context.
    """

    def __init__(self, *, rules: Optional[Iterable[ApplyRule]] = None):
        self._rules: Dict[int, ApplyRule] = {}
        self._overrides_matchers: DefaultDict[
            Optional[Type[ItemPage]], URLMatcher
        ] = defaultdict(URLMatcher)
        self._item_matchers: DefaultDict[Optional[Type], URLMatcher] = defaultdict(
            URLMatcher
        )

        # Ensures that URLMatcher is deterministic in returning a rule when
        # matching. As of url_macher==0.2.0, `url_matcher.URLMatcher._sort_domain`
        # has this sorting criteria:
        #   * Priority (descending)
        #   * Sorted list of includes for this domain (descending)
        #   * Rule identifier (descending)
        # This means that if the priority and domain are the same, the last tie
        # breaker would be the "Rule identifier", this means we can base it on
        # the order of rule addition to the registry, i.e. a counter.
        self._rule_counter = 0

        if rules is not None:
            for rule in rules:
                self.add_rule(rule)

    def add_rule(self, rule: ApplyRule) -> None:
        """Registers an :class:`web_poet.rules.ApplyRule` instance."""

        matched = self._item_matchers.get(rule.to_return)
        if matched:
            # A common case when a page object subclasses another one with the
            # same URL pattern.
            pattern_dupes = [
                pattern
                for pattern in matched.patterns.values()
                if pattern == rule.for_patterns
            ]
            if pattern_dupes:
                rules_to_warn = [
                    r
                    for p in pattern_dupes
                    for r in self.search(for_patterns=p, to_return=rule.to_return)
                ] + [rule]
                warnings.warn(
                    f"Similar URL patterns {pattern_dupes} were declared earlier "
                    f"that use to_return={rule.to_return}. The first, highest-priority "
                    f"rule added to the registry will be used when matching "
                    f"against URLs. Consider updating the priority of these rules: "
                    f"{rules_to_warn}."
                )

        self._rule_counter += 1
        rule_id = self._rule_counter

        self._overrides_matchers[rule.instead_of].add_or_update(
            rule_id, rule.for_patterns
        )
        self._item_matchers[rule.to_return].add_or_update(rule_id, rule.for_patterns)

        self._rules[rule_id] = rule

    @classmethod
    def from_override_rules(
        cls: Type[RulesRegistryTV], rules: List[ApplyRule]
    ) -> RulesRegistryTV:
        """Deprecated. Use ``RulesRegistry(rules=...)`` instead."""
        msg = (
            "The 'from_override_rules' method is deprecated. "
            "Use 'RulesRegistry(rules=...)' instead."
        )
        warnings.warn(msg, DeprecationWarning, stacklevel=2)
        return cls(rules=rules)

    def handle_urls(
        self,
        include: Strings,
        *,
        overrides: Optional[Type[ItemPage]] = None,
        instead_of: Optional[Type[ItemPage]] = None,
        to_return: Optional[Type] = None,
        exclude: Optional[Strings] = None,
        priority: int = 500,
        **kwargs,
    ):
        """
        Class decorator that indicates that the decorated Page Object should work
        for the given URL patterns.

        The URL patterns are matched using the ``include`` and ``exclude``
        parameters while ``priority`` breaks any ties. See the documentation
        of the `url-matcher <https://url-matcher.readthedocs.io/>`_ package for
        more information about them.

        This decorator is able to derive the item class returned by the Page
        Object (see :ref:`rules-item-class-example` section for some examples). This is
        important since it marks what type of item the Page Object is capable of
        returning for the given URL patterns. For certain advanced cases, you can
        pass a ``to_return`` parameter which replaces any derived values (though
        this isn't generally recommended).

        Passing another Page Object into the ``instead_of`` parameter indicates
        that the decorated Page Object will be used instead of that for the given
        set of URL patterns. This is the concept of **overrides** (see the
        :ref:`rules-intro-overrides` section for more info`).

        Any extra parameters are stored as meta information that can be later used.

        :param include: The URLs that should be handled by the decorated Page Object.
        :param instead_of: The Page Object that should be `replaced`.
        :param to_return: The item class holding the data returned by the Page Object.
            This could be omitted as it could be derived from the ``Returns[ItemClass]``
            or ``ItemPage[ItemClass]`` declaration of the Page Object. See
            :ref:`item-classes` section. Code example in :ref:`rules-combination` subsection.
        :param exclude: The URLs for which the Page Object should **not** be applied.
        :param priority: The resolution priority in case of `conflicting` rules.
            A conflict happens when the ``include``, ``override``, and ``exclude``
            parameters are the same. If so, the `highest priority` will be
            chosen.
        """

        def wrapper(cls):

            if overrides is not None:
                msg = (
                    "The 'overrides' parameter in @handle_urls is deprecated. "
                    "Use the 'instead_of' parameter instead. If both 'instead_of' "
                    "and 'overrides' are provided, the latter is ignored."
                )
                warnings.warn(msg, DeprecationWarning, stacklevel=2)

            rule = ApplyRule(
                for_patterns=Patterns(
                    include=as_list(include),
                    exclude=as_list(exclude),
                    priority=priority,
                ),
                use=cls,
                instead_of=instead_of or overrides,
                to_return=to_return or get_item_cls(cls),
                meta=kwargs,
            )
            self.add_rule(rule)
            return cls

        return wrapper

    def get_rules(self) -> List[ApplyRule]:
        """Return all the :class:`~.ApplyRule` that were declared using
        the ``@handle_urls`` decorator.

        .. note::

            Remember to consider calling :func:`~.web_poet.rules.consume_modules`
            beforehand to recursively import all submodules which contains the
            ``@handle_urls`` decorators from external Page Objects.
        """
        return list(self._rules.values())

    def get_overrides(self) -> List[ApplyRule]:
        """Deprecated, use :meth:`~.RulesRegistry.get_rules` instead."""
        msg = "The 'get_overrides' method is deprecated. Use 'get_rules' instead."
        warnings.warn(msg, DeprecationWarning, stacklevel=2)
        return self.get_rules()

    def search(self, **kwargs) -> List[ApplyRule]:
        """Return any :class:`ApplyRule` from the registry that matches with all
        the provided attributes.

        Sample usage:

        .. code-block:: python

            rules = registry.search(use=ProductPO, instead_of=GenericPO)
            print(len(rules))           # 1
            print(rules[0].use)         # ProductPO
            print(rules[0].instead_of)  # GenericPO

        """
        # Use a dict instead of set() to preserve the order.
        rule_ids = {}

        if "to_return" in kwargs:
            matcher = self._item_matchers.get(kwargs["to_return"])
            if matcher:
                rule_ids.update(matcher.patterns)

        if "instead_of" in kwargs:
            matcher = self._overrides_matchers.get(kwargs["instead_of"])
            if matcher:
                if rule_ids:
                    # If both params are used then narrow down the rules.
                    rule_ids = {
                        k: v for k, v in matcher.patterns.items() if k in rule_ids
                    }
                else:
                    rule_ids.update(matcher.patterns)

        rules = [self._rules[id_] for id_ in rule_ids]

        if rules and kwargs.keys() <= {"to_return", "instead_of"}:
            return rules

        # Search other parameters as well

        getter = attrgetter(*kwargs.keys())

        def finder(rule: ApplyRule):
            attribs = getter(rule)
            if not isinstance(attribs, tuple):
                attribs = (attribs,)
            if attribs == tuple(kwargs.values()):
                return True
            return False

        results = []
        for rule in rules or self.get_rules():
            if finder(rule):
                results.append(rule)
        return results

    def search_overrides(self, **kwargs) -> List[ApplyRule]:
        """Deprecated, use :meth:`~.RulesRegistry.search` instead."""
        msg = "The 'search_overrides' method is deprecated. Use 'search' instead."
        warnings.warn(msg, DeprecationWarning, stacklevel=2)
        return self.search(**kwargs)

    def _match_url_for_page_object(
        self, url: Union[_Url, str], matcher: Optional[URLMatcher] = None
    ) -> Optional[Type[ItemPage]]:
        """Returns the page object to use based on the URL and URLMatcher."""
        if not url or matcher is None:
            return None

        rule_id = matcher.match(str(url))
        if rule_id is not None:
            return self._rules[rule_id].use

    def overrides_for(
        self, url: Union[_Url, str]
    ) -> Mapping[Type[ItemPage], Type[ItemPage]]:
        """Finds all of the page objects associated with the given URL and
        returns a Mapping where the 'key' represents the page object that is
        **overridden** by the page object in 'value'.

        See example: :ref:`rules-overrides_for-example`.
        """
        result: Dict[Type[ItemPage], Type[ItemPage]] = {}
        for target, matcher in self._overrides_matchers.items():
            if target is None:
                continue
            po = self._match_url_for_page_object(url, matcher)
            if po:
                result[target] = po
        return result

    def page_object_for_item(
        self, url: Union[_Url, str], item_cls: Type
    ) -> Optional[Type]:
        """Return the page object class associated with the given URL that's able
        to produce the given ``item_cls``.

        See example: :ref:`rules-page_object_for_item-example`.
        """
        if item_cls is None:
            return None
        matcher = self._item_matchers.get(item_cls)
        return self._match_url_for_page_object(url, matcher)


def _walk_module(module: str) -> Iterable:
    """Return all modules from a module recursively.

    Note that this will import all the modules and submodules. It returns the
    provided module as well.
    """

    def onerror(err):
        raise err  # pragma: no cover

    spec = importlib.util.find_spec(module)
    if not spec:
        raise ImportError(f"Module {module} not found")
    mod = importlib.import_module(spec.name)
    yield mod
    if spec.submodule_search_locations:
        for info in pkgutil.walk_packages(
            spec.submodule_search_locations, f"{spec.name}.", onerror
        ):
            mod = importlib.import_module(info.name)
            yield mod


def consume_modules(*modules: str) -> None:
    """This recursively imports all packages/modules so that the ``@handle_urls``
    decorators are properly discovered and imported.

    Let's take a look at an example:

    .. code-block:: python

        # FILE: my_page_obj_project/load_rules.py

        from web_poet import default_registry, consume_modules

        consume_modules("other_external_pkg.po", "another_pkg.lib")
        rules = default_registry.get_rules()

    For this case, the :class:`~.ApplyRule` are coming from:

        - ``my_page_obj_project`` `(since it's the same module as the file above)`
        - ``other_external_pkg.po``
        - ``another_pkg.lib``
        - any other modules that was imported in the same process inside the
          packages/modules above.

    If the ``default_registry`` had other ``@handle_urls`` decorators outside of
    the packages/modules listed above, then the corresponding :class:`~.ApplyRule`
    won't be returned. Unless, they were recursively imported in some way similar
    to :func:`~.web_poet.rules.consume_modules`.
    """

    for module in modules:
        gen = _walk_module(module)

        # Inspired by itertools recipe: https://docs.python.org/3/library/itertools.html
        # Using a deque() results in a tiny bit performance improvement that list().
        deque(gen, maxlen=0)


OverrideRule = _create_deprecated_class("OverrideRule", ApplyRule, warn_once=False)
PageObjectRegistry = _create_deprecated_class(
    "PageObjectRegistry", RulesRegistry, warn_once=True
)
