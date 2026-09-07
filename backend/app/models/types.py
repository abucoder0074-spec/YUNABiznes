"""Database numeric precision shared by accounting models."""

from sqlalchemy import Numeric

MONEY = Numeric(18, 2)
QUANTITY = Numeric(18, 4)
