from app.domain.challenges import (
    ONCE_PERIOD_KEY,
    Challenge,
    ChallengeClaimError,
    ChallengeClaimRefusal,
    ChallengeKind,
    ChallengePeriod,
)


def test_once_period_key_is_a_constant_not_a_calendar_key() -> None:
    assert ONCE_PERIOD_KEY == "ONCE"


def test_challenge_is_a_plain_frozen_record() -> None:
    challenge = Challenge(
        id="choose_team",
        kind=ChallengeKind.TEAM_CHOICE,
        period=ChallengePeriod.ONCE,
        target=1,
        reward_coins=30,
        active=True,
    )
    assert challenge.kind is ChallengeKind.TEAM_CHOICE
    assert challenge.period is ChallengePeriod.ONCE


def test_claim_error_carries_the_refusal_reason_and_progress() -> None:
    error = ChallengeClaimError(ChallengeClaimRefusal.NOT_UNLOCKED, required=3, have=1)
    assert error.reason is ChallengeClaimRefusal.NOT_UNLOCKED
    assert (error.required, error.have) == (3, 1)


def test_claim_error_defaults_required_and_have_to_none() -> None:
    error = ChallengeClaimError(ChallengeClaimRefusal.ALREADY_CLAIMED)
    assert (error.required, error.have) == (None, None)
