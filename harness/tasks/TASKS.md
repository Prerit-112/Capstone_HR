# Harness tasks

| id | family | verifier | intent |
|----|--------|----------|--------|
| bar_suryodaya | core | bar | Exact Section 8 bar request |
| cap_lop_summary | capability | bar | Same three capabilities, different wording |
| cap_exceptions_brief | capability | bar | Planning brief wording (anti-overfit) |
| cap_balance_check | capability | balances | LeaveBalance vs LeaveType (empty catalogue = honest gap) |
| cap_holiday_week_leave | capability | holiday_week | Holiday child dates + leave + present-on-holiday |
| robust_as_of_window | robustness | bar | Injected as_of=2026-09-18 |
| write_fix_attendance | write | write | Guarded Attendance.update + live status check |
| write_conflict_abort | write | write_conflict | Shared-book re-read abort (harness poisons the row) |
| refuse_out_of_seat | refusal | refusal | Manufacturing WO — seat boundary |
| refuse_approve_leave | refusal | refusal | Approve path missing / admin-only |
| refuse_unsupported_lateness | refusal | refusal | No clock-in / root-cause capture stack |

Reachability:

- Out-of-seat: WorkOrder tools absent from team13 catalogue → refuse + escalate.
- Approve: no approve* in tools/list; REST requires admin (see bug_findings.md).
- Lateness root cause: no geofence/punch-source fields on Attendance — platform gap from gap_report.md.
- HolidayList / LeaveType empty on Suryodaya: not a platform bug; agent must not invent data.
