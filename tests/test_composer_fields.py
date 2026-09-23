"""번들 필드를 읽는 규율 — `BOUNDARY.md` §3.2, `AGENT-01` §3 원칙 2."""

import pytest

from composer.fields import ABSENT, read_field


def test_키_부재와_null_을_같게_다루지_않는다():
    """`null` 은 「값이 없다」이고, 키 부재는 「이 판이 그 필드를 안 낸다」다.

    접으면 적재 형식이 바뀐 것을 관측 실패로도, 정상으로도 읽게 된다.
    """
    assert read_field({"failureClass": None}, "failureClass") is None
    assert read_field({}, "failureClass") is ABSENT
