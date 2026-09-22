"""检索前查询授权测试。"""

from __future__ import annotations

import unittest

from netops_copilot.application.authorization import QueryAuthorizationError, authorize_query
from netops_copilot.application.ports.search import SearchFilters
from netops_copilot.domain.shared.identity import Principal, SecurityLevel


class QueryAuthorizationTests(unittest.TestCase):
    def test_normalizes_query_and_preserves_vendor_version_site_filters(self) -> None:
        principal = Principal("basic", SecurityLevel.BASIC, frozenset({"site-gz-dc"}))
        authorized = authorize_query(
            principal,
            "  Huawei   OSPF\tExStart ",
            SearchFilters(site_id="site-gz-dc", vendor="Huawei", os_version="V200R022"),
        )
        self.assertEqual(authorized.query, "Huawei OSPF ExStart")
        self.assertEqual(authorized.filters.vendor, "Huawei")
        self.assertEqual(authorized.filters.os_version, "V200R022")

    def test_basic_principal_cannot_receive_restricted_evidence(self) -> None:
        basic = Principal("basic", SecurityLevel.BASIC, frozenset({"site-gz-dc"}))
        restricted = Principal("restricted", SecurityLevel.RESTRICTED, frozenset({"site-gz-dc"}))
        filters = SearchFilters(site_id="site-gz-dc", security_level="restricted")
        with self.assertRaises(QueryAuthorizationError):
            authorize_query(basic, "restricted SOP", filters)
        self.assertEqual(authorize_query(restricted, "restricted SOP", filters).query, "restricted SOP")

    def test_site_filter_is_required_and_out_of_scope_is_denied(self) -> None:
        principal = Principal("basic", SecurityLevel.BASIC, frozenset({"site-gz-dc"}))
        with self.assertRaises(QueryAuthorizationError):
            authorize_query(principal, "OSPF", SearchFilters())
        with self.assertRaises(QueryAuthorizationError):
            authorize_query(principal, "OSPF", SearchFilters(site_id="site-sh-branch"))
