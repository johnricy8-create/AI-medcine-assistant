"""预算状态测试。"""

from __future__ import annotations

import unittest

from app.graph.state import BudgetState


class TestBudget(unittest.TestCase):
    def test_consumption_and_limits(self) -> None:
        budget = BudgetState(max_retrievals=3, max_tool_calls=1)
        self.assertTrue(budget.can_retrieve(3))
        budget.consume_retrievals(2)
        self.assertTrue(budget.can_retrieve(1))
        self.assertFalse(budget.can_retrieve(2))
        budget.consume_tool_calls(1)
        self.assertFalse(budget.can_call_tool(1))

    def test_plan_rounds(self) -> None:
        budget = BudgetState(max_plan_rounds=2)
        self.assertTrue(budget.can_plan())
        budget.consume_plan()
        budget.consume_plan()
        self.assertFalse(budget.can_plan())

    def test_timeout(self) -> None:
        budget = BudgetState(max_task_seconds=0)
        budget.started_at -= 1
        self.assertTrue(budget.timed_out())


if __name__ == "__main__":
    unittest.main()
