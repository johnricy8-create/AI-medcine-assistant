"""ACL 服务测试。"""

from __future__ import annotations

import unittest

from app.config import PROJECT_ROOT
from app.services.acl import AccessService


class TestAccessService(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        acl_dir = PROJECT_ROOT / "data" / "internal_demo" / "acl"
        cls.acl = AccessService.from_files(
            acl_dir / "users.yaml",
            acl_dir / "projects.yaml",
        )

    def test_ibd_scientist_scopes(self) -> None:
        context = self.acl.context("scientist_031", "IBD-TX-07")
        self.assertTrue(context.project_allowed)
        self.assertIn("public", context.allowed_scopes)
        self.assertIn("project:IBD-TX-07", context.allowed_scopes)
        self.assertNotIn("project:ONCO-02", context.allowed_scopes)
        self.assertTrue(context.can_access("project:IBD-TX-07"))
        self.assertFalse(context.can_access("project:ONCO-02"))

    def test_onco_scientist_scopes(self) -> None:
        context = self.acl.context("scientist_045", "ONCO-02")
        self.assertTrue(context.project_allowed)
        self.assertIn("project:ONCO-02", context.allowed_scopes)
        self.assertNotIn("project:IBD-TX-07", context.allowed_scopes)

    def test_guest_only_public(self) -> None:
        context = self.acl.context("guest", "IBD-TX-07")
        self.assertFalse(context.project_allowed)
        self.assertEqual(context.allowed_scopes, ["public"])

    def test_unknown_user_only_public(self) -> None:
        context = self.acl.context("unknown", "IBD-TX-07")
        self.assertFalse(context.user_known)
        self.assertFalse(context.project_allowed)
        self.assertEqual(context.allowed_scopes, ["public"])

    def test_reviewer_both_projects(self) -> None:
        context = self.acl.context("reviewer_001", "ONCO-02")
        self.assertTrue(context.project_allowed)
        self.assertIn("project:IBD-TX-07", context.allowed_scopes)
        self.assertIn("project:ONCO-02", context.allowed_scopes)


if __name__ == "__main__":
    unittest.main()
