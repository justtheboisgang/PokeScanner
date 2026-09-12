"""Shared SQLAlchemy enum type definitions.

Non-native (VARCHAR + CHECK) on purpose: it round-trips on the enum *value*
(e.g. "de", "played"), can be reused across tables (Channel appears in three)
without Postgres native-enum type collisions, and keeps migrations trivial.

Using these exact instances in both the models and the migration guarantees the
schema matches the ORM.
"""

from __future__ import annotations

import enum

import sqlalchemy as sa


def _values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def enum_type(enum_cls: type[enum.Enum], name: str) -> sa.Enum:
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        values_callable=_values,
    )
