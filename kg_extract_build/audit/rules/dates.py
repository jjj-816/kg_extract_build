"""日期解析与确定性时序判断。"""

from __future__ import annotations

from datetime import datetime
import re

DATE_RE = re.compile(r"(20\d{2})[年\-/.](\d{1,2})[月\-/.](\d{1,2})")


def parse_dates(text: str) -> tuple[datetime, ...]:
    values = []
    for match in DATE_RE.finditer(text):
        try:
            values.append(datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    return tuple(values)


def is_chronological(start: datetime, end: datetime) -> bool:
    return start <= end
