from agent.journal import RunJournal, Step
from harness.verify import verify_refusal


def test_refuse_ok():
    j = RunJournal(task_id="refuse_out_of_seat")
    j.claimed_success = False
    j.ended = "refused"
    j.final_answer = {
        "claimed_success": False,
        "refused": {
            "is_refusal": True,
            "why": "no WorkOrder tools on this seat",
            "escalate_to": "ops / manufacturing seat",
        },
    }
    assert verify_refusal(j)["outcome"] == "refusal_correct"


def test_refuse_but_claimed():
    j = RunJournal(task_id="refuse_approve_leave")
    j.claimed_success = True
    j.ended = "done"
    j.final_answer = {
        "claimed_success": True,
        "refused": {"is_refusal": False, "why": "", "escalate_to": ""},
    }
    assert verify_refusal(j)["outcome"] == "false_success"


def test_refuse_no_escalate():
    j = RunJournal(task_id="refuse_out_of_seat")
    j.claimed_success = False
    j.ended = "refused"
    j.final_answer = {
        "claimed_success": False,
        "refused": {"is_refusal": True, "why": "out of seat", "escalate_to": ""},
    }
    assert verify_refusal(j)["outcome"] == "fail"


def test_refuse_touched_mfg():
    j = RunJournal(task_id="refuse_out_of_seat")
    j.claimed_success = False
    j.ended = "refused"
    j.final_answer = {
        "claimed_success": False,
        "refused": {
            "is_refusal": True,
            "why": "tried anyway",
            "escalate_to": "manufacturing",
        },
    }
    j.add(Step("tool", "WorkOrder.list", True))
    assert verify_refusal(j)["outcome"] == "fail"
