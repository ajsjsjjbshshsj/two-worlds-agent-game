"""Stable additive indexes. Conflicts must fail, never drop or weaken an index."""

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.database import Database


def ensure_indexes(database: Database) -> None:
    database.accounts.create_indexes(
        [
            IndexModel(
                [("email", ASCENDING)],
                unique=True,
                name="accounts_email_unique",
            ),
            IndexModel(
                [("sessions.token_digest", ASCENDING)],
                unique=True,
                name="accounts_session_unique",
                # Empty session arrays must not compete for a unique null key.
                partialFilterExpression={"sessions.token_digest": {"$type": "string"}},
            ),
        ]
    )
    database.verification_codes.create_indexes(
        [
            IndexModel(
                [("email", ASCENDING), ("purpose", ASCENDING)],
                unique=True,
                name="verification_email_purpose_unique",
            ),
            IndexModel([("expires_at", ASCENDING)], name="verification_expiry"),
        ]
    )
    database.rate_limits.create_indexes(
        [IndexModel([("expires_at", ASCENDING)], name="rate_expiry")]
    )
    database.pairs.create_indexes(
        [
            IndexModel(
                [("invite_digest", ASCENDING)], unique=True, name="pairs_invite_unique"
            ),
            IndexModel([("member_a", ASCENDING)], name="pairs_member_a"),
            IndexModel([("member_b", ASCENDING)], name="pairs_member_b"),
        ]
    )
    database.saves.create_indexes(
        [
            IndexModel(
                [("pair_id", ASCENDING), ("script_id", ASCENDING)],
                unique=True,
                name="saves_pair_script_unique",
            ),
            IndexModel(
                [("pair_id", ASCENDING), ("updated_at", DESCENDING)],
                name="saves_pair_updated",
            ),
        ]
    )
