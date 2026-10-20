"""Pure referral rules: bind refusal and settle payout computation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.referrals import (
    FIRST_CODE_BONUS_COINS,
    LATER_CODE_BONUS_COINS,
    LATER_CODE_WINDOW,
    ReferralBindError,
    ReferralBindRefusal,
    check_can_bind,
    first_code_bonus_key,
    generate_referral_code,
    later_code_bonus_key,
    settle_payouts,
)


def _now() -> datetime:
    return datetime(2026, 10, 20, tzinfo=UTC)


def test_generate_referral_code_is_eight_crockford_characters() -> None:
    import random

    code = generate_referral_code(random.Random(1))
    assert len(code) == 8
    for forbidden in "ILOU":
        assert forbidden not in code


def test_check_can_bind_rejects_unknown_code() -> None:
    invitee = uuid4()
    with pytest.raises(ReferralBindError) as excinfo:
        check_can_bind(invitee, None, already_bound=False, invitee_redeemed_codes=0)
    assert excinfo.value.reason is ReferralBindRefusal.CODE_UNKNOWN


def test_check_can_bind_rejects_self_referral() -> None:
    user = uuid4()
    with pytest.raises(ReferralBindError) as excinfo:
        check_can_bind(user, user, already_bound=False, invitee_redeemed_codes=0)
    assert excinfo.value.reason is ReferralBindRefusal.SELF


def test_check_can_bind_rejects_a_second_bind() -> None:
    invitee, inviter = uuid4(), uuid4()
    with pytest.raises(ReferralBindError) as excinfo:
        check_can_bind(invitee, inviter, already_bound=True, invitee_redeemed_codes=0)
    assert excinfo.value.reason is ReferralBindRefusal.ALREADY_BOUND


def test_check_can_bind_rejects_binding_after_codes_exist() -> None:
    invitee, inviter = uuid4(), uuid4()
    with pytest.raises(ReferralBindError) as excinfo:
        check_can_bind(invitee, inviter, already_bound=False, invitee_redeemed_codes=1)
    assert excinfo.value.reason is ReferralBindRefusal.TOO_LATE


def test_check_can_bind_allows_a_fresh_valid_bind() -> None:
    invitee, inviter = uuid4(), uuid4()
    check_can_bind(invitee, inviter, already_bound=False, invitee_redeemed_codes=0)


def test_settle_payouts_pays_nothing_while_mission_incomplete() -> None:
    invitee = uuid4()
    payouts = settle_payouts(
        invitee,
        mission_complete=False,
        redeemed_codes=[(uuid4(), _now())],
    )
    assert payouts == []


def test_settle_payouts_pays_nothing_without_any_code_yet() -> None:
    invitee = uuid4()
    payouts = settle_payouts(invitee, mission_complete=True, redeemed_codes=[])
    assert payouts == []


def test_settle_payouts_pays_first_code_bonus_once_mission_complete() -> None:
    invitee = uuid4()
    first_id = uuid4()
    payouts = settle_payouts(
        invitee, mission_complete=True, redeemed_codes=[(first_id, _now())]
    )
    assert len(payouts) == 1
    assert payouts[0].amount == FIRST_CODE_BONUS_COINS
    assert payouts[0].idempotency_key == first_code_bonus_key(invitee)


def test_settle_payouts_pays_first_and_later_codes_at_once() -> None:
    invitee = uuid4()
    first_id, second_id, third_id = uuid4(), uuid4(), uuid4()
    now = _now()
    codes = [
        (first_id, now),
        (second_id, now + timedelta(days=1)),
        (third_id, now + timedelta(days=2)),
    ]
    payouts = settle_payouts(invitee, mission_complete=True, redeemed_codes=codes)
    assert [p.amount for p in payouts] == [
        FIRST_CODE_BONUS_COINS,
        LATER_CODE_BONUS_COINS,
        LATER_CODE_BONUS_COINS,
    ]
    assert payouts[0].idempotency_key == first_code_bonus_key(invitee)
    assert payouts[1].idempotency_key == later_code_bonus_key(second_id)
    assert payouts[2].idempotency_key == later_code_bonus_key(third_id)


def test_settle_payouts_excludes_a_later_code_outside_the_window() -> None:
    invitee = uuid4()
    first_id, late_id = uuid4(), uuid4()
    now = _now()
    codes = [
        (first_id, now),
        (late_id, now + LATER_CODE_WINDOW + timedelta(days=1)),
    ]
    payouts = settle_payouts(invitee, mission_complete=True, redeemed_codes=codes)
    assert len(payouts) == 1
    assert payouts[0].idempotency_key == first_code_bonus_key(invitee)
