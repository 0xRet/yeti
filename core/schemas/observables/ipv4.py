from core.schemas.observable import Observable
from core.schemas.observable import ObservableType
from typing import Literal


class IPv4(Observable):
    value: str
    type: ObservableType = ObservableType.ipv4
