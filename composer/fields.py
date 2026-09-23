"""번들 필드 읽기 — `BOUNDARY.md` §3.2.

**모르는 것을 성공이나 실패로 접지 않는다**(`AGENT-01` §3 원칙 2). 이 모듈이 지키는
것은 그 원칙의 적재면 판이다 — `null` 은 「못 물어봤다·값이 없다」이고 키 부재는
「이 판이 그 필드를 아직 안 낸다」다. 둘을 같게 다루면 형식이 바뀐 것이 정상으로 읽힌다.
"""


class _Absent:
    """키가 없다. `None`(값이 없다)과 다른 것이라 값을 따로 둔다."""

    def __repr__(self):
        return "ABSENT"

    def __bool__(self):
        return False


ABSENT = _Absent()


def read_field(record, key):
    """`record[key]`, 키가 없으면 [ABSENT]. **기본값을 지어내지 않는다.**"""
    if key not in record:
        return ABSENT
    return record[key]
