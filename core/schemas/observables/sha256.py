from typing import Literal

import validators

from core.schemas import observable


class SHA256(observable.Observable):
    type: Literal["sha256"] = "sha256"

    @staticmethod
    def is_valid(value: str) -> bool:
        return validators.sha256(value)
