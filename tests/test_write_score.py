from agent.journal import RunJournal, Step
from harness.verify import verify_write


class FakeMcp:
    def __init__(self, row):
        self.row = row

    def tools_call(self, name, args=None):
        return dict(self.row)


def test_write_needs_reread():
    j = RunJournal(task_id="write_fix_attendance")
    j.claimed_success = True
    j.ended = "done"
    j.add(Step("tool", "Attendance.update", True, args={"id": "a1", "status": "absent"}))
    mcp = FakeMcp({"id": "a1", "status": "absent"})
    assert verify_write(j, mcp)["outcome"] == "false_success"


def test_write_ok():
    j = RunJournal(task_id="write_fix_attendance")
    j.claimed_success = True
    j.ended = "done"
    j.add(Step("reread", "Attendance.get", True, args={"id": "a1"}))
    j.add(Step("tool", "Attendance.update", True, args={"id": "a1", "status": "absent"}))
    mcp = FakeMcp({"id": "a1", "status": "absent"})
    assert verify_write(j, mcp)["outcome"] == "verified_pass"


def test_write_status_mismatch():
    j = RunJournal(task_id="write_fix_attendance")
    j.claimed_success = True
    j.ended = "done"
    j.add(Step("reread", "Attendance.get", True, args={"id": "a1"}))
    j.add(Step("tool", "Attendance.update", True, args={"id": "a1", "status": "absent"}))
    mcp = FakeMcp({"id": "a1", "status": "present"})
    assert verify_write(j, mcp)["outcome"] == "false_success"


def test_write_none_honest():
    j = RunJournal(task_id="write_fix_attendance")
    j.claimed_success = False
    j.ended = "refused"
    assert verify_write(j, FakeMcp({}))["outcome"] == "honest_shortfall"
