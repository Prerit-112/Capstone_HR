from agent.gemini_compat import has_thought_signature, serialize_tool_calls


class _Fn:
    def __init__(self, name, args):
        self.name = name
        self.arguments = args


class _TC:
    def __init__(self, sig="SIG123", in_dump=False):
        self.id = "call_1"
        self.type = "function"
        self.function = _Fn("Attendance__list", '{"limit":1}')
        self._sig = sig
        self._in_dump = in_dump
        self.model_extra = {"extra_content": {"google": {"thought_signature": sig}}}

    def model_dump(self, exclude_none=True):
        d = {
            "id": self.id,
            "type": self.type,
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }
        if self._in_dump:
            d["extra_content"] = {"google": {"thought_signature": self._sig}}
        return d


def test_sig_from_extra():
    out = serialize_tool_calls([_TC()])
    assert has_thought_signature(out[0])
    assert out[0]["extra_content"]["google"]["thought_signature"] == "SIG123"


def test_sig_in_dump():
    out = serialize_tool_calls([_TC(sig="SIG456", in_dump=True)])
    assert out[0]["extra_content"]["google"]["thought_signature"] == "SIG456"
