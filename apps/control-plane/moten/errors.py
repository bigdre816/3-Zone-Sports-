"""Domain errors mapped to fail-closed HTTP responses (AGENTS.md §2.7)."""


class MotenError(Exception):
    status_code = 400


class GuardViolation(MotenError):
    """A lifecycle guard or invariant blocked the action (fail closed)."""

    status_code = 409


class TwoPersonRequired(MotenError):
    """An irreversible action requires a distinct second human approver."""

    status_code = 409


class NotNaturalPerson(MotenError):
    """Only natural persons may be inventors/contributors (spec §06)."""

    status_code = 422


class DisclosureBlocked(MotenError):
    """Disclosure preflight blocked a prohibited release."""

    status_code = 409


class NotFound(MotenError):
    status_code = 404
