from backend.app.services.reviewer_identity_service import (
    ReviewerAuthenticationRequired,
    ReviewerAuthorizationError,
    ReviewerIdentityService,
)


# ==========================================================
# ASSERT HELPERS
# ==========================================================

def assert_equal(
    actual,
    expected,
    message: str,
):

    if actual != expected:

        raise AssertionError(
            f"{message}\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


def expect_exception(
    exception_type,
    function,
    message: str,
):

    try:

        function()

    except exception_type:

        return


    raise AssertionError(
        message
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print()
    print("=" * 76)
    print(
        "PHASE 7C.5a — REVIEWER "
        "IDENTITY FOUNDATION TEST"
    )
    print("=" * 76)


    # ======================================================
    # TEST 1 — LOCAL SERVER IDENTITY
    # ======================================================

    print()
    print("-" * 76)
    print(
        "TEST 1 — LOCAL SERVER-CONFIGURED IDENTITY"
    )
    print("-" * 76)


    service = (
        ReviewerIdentityService(
            mode=(
                "local_env"
            ),

            local_reviewer_id=(
                "local-reviewer-001"
            ),

            local_reviewer_role=(
                "REVIEWER"
            ),
        )
    )


    identity = (
        service.resolve_reviewer(
            headers={
                # Deliberate spoof attempt.
                "X-VIGILOX-REVIEWER-ID":
                    "spoofed-user",

                "X-VIGILOX-REVIEWER-ROLE":
                    "ADMIN",
            }
        )
    )


    assert_equal(
        identity.reviewer_id,
        "local-reviewer-001",
        (
            "LOCAL_ENV mode must use "
            "server-configured reviewer ID."
        ),
    )


    assert_equal(
        identity.role,
        "REVIEWER",
        (
            "LOCAL_ENV mode must use "
            "server-configured role."
        ),
    )


    assert_equal(
        identity.source,
        "LOCAL_ENV",
        (
            "Unexpected local identity "
            "source."
        ),
    )


    print(
        "[PASS] LOCAL_ENV identity comes "
        "from server configuration"
    )

    print(
        "[PASS] Client header spoof attempt "
        "cannot replace local identity"
    )


    # ======================================================
    # TEST 2 — TRUSTED REVIEWER HEADER
    # ======================================================

    print()
    print("-" * 76)
    print(
        "TEST 2 — TRUSTED HEADER REVIEWER"
    )
    print("-" * 76)


    service = (
        ReviewerIdentityService(
            mode=(
                "trusted_headers"
            )
        )
    )


    identity = (
        service.resolve_reviewer(
            headers={
                "x-vigilox-reviewer-id":
                    "reviewer-002",

                "x-vigilox-reviewer-role":
                    "reviewer",
            }
        )
    )


    assert_equal(
        identity.reviewer_id,
        "reviewer-002",
        (
            "Trusted header reviewer ID "
            "was not resolved correctly."
        ),
    )


    assert_equal(
        identity.role,
        "REVIEWER",
        (
            "Reviewer role should "
            "normalize to uppercase."
        ),
    )


    assert_equal(
        identity.source,
        "TRUSTED_HEADER",
        (
            "Unexpected trusted-header "
            "identity source."
        ),
    )


    print(
        "[PASS] Trusted reviewer headers "
        "resolve identity"
    )


    # ======================================================
    # TEST 3 — ADMIN AUTHORIZED
    # ======================================================

    print()
    print("-" * 76)
    print(
        "TEST 3 — ADMIN REVIEW AUTHORIZATION"
    )
    print("-" * 76)


    identity = (
        service.resolve_reviewer(
            headers={
                "X-VIGILOX-REVIEWER-ID":
                    "admin-001",

                "X-VIGILOX-REVIEWER-ROLE":
                    "ADMIN",
            }
        )
    )


    assert_equal(
        identity.role,
        "ADMIN",
        (
            "ADMIN role was not "
            "resolved correctly."
        ),
    )


    print(
        "[PASS] ADMIN can submit "
        "human review decisions"
    )


    # ======================================================
    # TEST 4 — VIEWER DENIED WRITE ACCESS
    # ======================================================

    print()
    print("-" * 76)
    print(
        "TEST 4 — VIEWER WRITE DENIAL"
    )
    print("-" * 76)


    expect_exception(
        ReviewerAuthorizationError,

        lambda: (
            service.resolve_reviewer(
                headers={
                    "X-VIGILOX-REVIEWER-ID":
                        "viewer-001",

                    "X-VIGILOX-REVIEWER-ROLE":
                        "VIEWER",
                }
            )
        ),

        (
            "VIEWER should not be able "
            "to submit human reviews."
        ),
    )


    print(
        "[PASS] VIEWER cannot submit "
        "human review decisions"
    )


    # ======================================================
    # TEST 5 — MISSING AUTHENTICATED IDENTITY
    # ======================================================

    print()
    print("-" * 76)
    print(
        "TEST 5 — MISSING IDENTITY"
    )
    print("-" * 76)


    expect_exception(
        ReviewerAuthenticationRequired,

        lambda: (
            service.resolve_reviewer(
                headers={
                    "X-VIGILOX-REVIEWER-ROLE":
                        "REVIEWER",
                }
            )
        ),

        (
            "Missing reviewer identity "
            "should be rejected."
        ),
    )


    print(
        "[PASS] Missing reviewer identity "
        "is rejected"
    )


    # ======================================================
    # TEST 6 — INVALID ROLE
    # ======================================================

    print()
    print("-" * 76)
    print(
        "TEST 6 — INVALID ROLE"
    )
    print("-" * 76)


    expect_exception(
        ReviewerAuthorizationError,

        lambda: (
            service.resolve_reviewer(
                headers={
                    "X-VIGILOX-REVIEWER-ID":
                        "unknown-user",

                    "X-VIGILOX-REVIEWER-ROLE":
                        "SUPERUSER",
                }
            )
        ),

        (
            "Unknown reviewer role "
            "should be rejected."
        ),
    )


    print(
        "[PASS] Unsupported role "
        "is rejected"
    )


    # ======================================================
    # TEST 7 — LOCAL MODE REQUIRES SERVER IDENTITY
    # ======================================================

    print()
    print("-" * 76)
    print(
        "TEST 7 — LOCAL MODE FAILS CLOSED"
    )
    print("-" * 76)


    local_without_user = (
        ReviewerIdentityService(
            mode=(
                "local_env"
            ),

            local_reviewer_id=(
                ""
            ),

            local_reviewer_role=(
                "REVIEWER"
            ),
        )
    )


    expect_exception(
        ReviewerAuthenticationRequired,

        lambda: (
            local_without_user
            .resolve_reviewer()
        ),

        (
            "LOCAL_ENV without a "
            "server-configured reviewer "
            "must fail closed."
        ),
    )


    print(
        "[PASS] LOCAL_ENV without "
        "configured identity fails closed"
    )


    # ======================================================
    # FINAL
    # ======================================================

    print()
    print("=" * 76)
    print(
        "[PASS] PHASE 7C.5a REVIEWER "
        "IDENTITY FOUNDATION TEST PASSED"
    )
    print("=" * 76)


if __name__ == "__main__":

    main()