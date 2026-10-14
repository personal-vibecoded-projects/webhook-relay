import base64
import json
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import tuple_


def paginate(statement, model, cursor, limit, id_field="id"):
    if cursor:
        try:
            data = json.loads(
                base64.b64decode(
                    cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
                )
            )
            at, identifier = datetime.fromisoformat(data["at"]), UUID(data["id"])
            if at.utcoffset() is None:
                raise ValueError
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise HTTPException(422, "Invalid pagination cursor") from None
        statement = statement.where(
            tuple_(model.created_at, getattr(model, id_field)) < tuple_(at, identifier)
        )
    return statement.order_by(
        model.created_at.desc(), getattr(model, id_field).desc()
    ).limit(limit + 1)


def next_cursor(rows, limit, id_field="id"):
    if len(rows) <= limit:
        return None
    last = rows[limit - 1]
    encoded = json.dumps(
        {"at": last.created_at.isoformat(), "id": str(getattr(last, id_field))}
    ).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")
