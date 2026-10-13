import pytest

from app.retry import RetryPolicy, call_with_retries, parse_retry_after


class FakeError(Exception):
    def __init__(self, retryable: bool, retry_after: float | None = None) -> None:
        super().__init__("fake")
        self.retryable = retryable
        self.retry_after = retry_after


def make_policy(sleeps: list[float], **kwargs: float) -> RetryPolicy:
    """A policy that records waits instead of sleeping and applies no jitter."""
    return RetryPolicy(sleep=sleeps.append, jitter=lambda delay: delay, **kwargs)  # type: ignore[arg-type]


def failing_then_ok(failures: list[Exception]):
    """A function that raises each error in turn, then returns "ok". Counts its calls."""
    calls: list[int] = []

    def func() -> str:
        calls.append(1)
        if len(calls) <= len(failures):
            raise failures[len(calls) - 1]
        return "ok"

    return func, calls


def test_success_on_first_try_does_not_sleep() -> None:
    sleeps: list[float] = []
    func, calls = failing_then_ok([])

    assert call_with_retries(func, make_policy(sleeps)) == "ok"
    assert len(calls) == 1
    assert sleeps == []


def test_retryable_error_is_retried_until_it_succeeds() -> None:
    sleeps: list[float] = []
    func, calls = failing_then_ok([FakeError(True), FakeError(True)])

    assert call_with_retries(func, make_policy(sleeps)) == "ok"
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]  # exponential: base, then double


def test_gives_up_after_max_attempts_and_raises_the_last_error() -> None:
    sleeps: list[float] = []
    errors = [FakeError(True), FakeError(True), FakeError(True), FakeError(True)]
    func, calls = failing_then_ok(errors)

    with pytest.raises(FakeError) as raised:
        call_with_retries(func, make_policy(sleeps, max_attempts=3))

    assert raised.value is errors[2]  # the third (last allowed) failure, unchanged
    assert len(calls) == 3
    assert len(sleeps) == 2  # no sleep after the final attempt


def test_non_retryable_error_is_raised_immediately() -> None:
    sleeps: list[float] = []
    error = FakeError(False)
    func, calls = failing_then_ok([error])

    with pytest.raises(FakeError) as raised:
        call_with_retries(func, make_policy(sleeps))

    assert raised.value is error
    assert len(calls) == 1
    assert sleeps == []


def test_errors_without_a_retryable_flag_are_not_retried() -> None:
    sleeps: list[float] = []
    func, calls = failing_then_ok([ValueError("plain error")])

    with pytest.raises(ValueError, match="plain error"):
        call_with_retries(func, make_policy(sleeps))

    assert len(calls) == 1


def test_delay_is_capped_at_max_delay() -> None:
    sleeps: list[float] = []
    func, _ = failing_then_ok([FakeError(True)] * 4)

    call_with_retries(func, make_policy(sleeps, max_attempts=5, base_delay=2.0, max_delay=5.0))

    assert sleeps == [2.0, 4.0, 5.0, 5.0]


def test_retry_after_replaces_backoff_and_is_capped() -> None:
    sleeps: list[float] = []
    func, _ = failing_then_ok([FakeError(True, retry_after=2.0), FakeError(True, retry_after=60.0)])

    call_with_retries(func, make_policy(sleeps, max_delay=5.0))

    assert sleeps == [2.0, 5.0]


def test_jitter_is_applied_to_backoff() -> None:
    sleeps: list[float] = []
    policy = RetryPolicy(sleep=sleeps.append, jitter=lambda delay: delay / 2)
    func, _ = failing_then_ok([FakeError(True)])

    call_with_retries(func, policy)

    assert sleeps == [0.25]


def test_default_jitter_stays_between_half_and_full_delay() -> None:
    sleeps: list[float] = []
    policy = RetryPolicy(sleep=sleeps.append)
    func, _ = failing_then_ok([FakeError(True)] * 2)

    call_with_retries(func, policy)

    assert 0.25 <= sleeps[0] <= 0.5
    assert 0.5 <= sleeps[1] <= 1.0


def test_policy_requires_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("2", 2.0),
        (" 1.5 ", 1.5),
        ("0", 0.0),
        ("-1", None),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
        ("soon", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_retry_after(header: str | None, expected: float | None) -> None:
    assert parse_retry_after(header) == expected
