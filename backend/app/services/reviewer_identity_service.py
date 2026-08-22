from dataclasses import (
    dataclass,
)

from os import (
    getenv,
)

from typing import (
    Mapping,
)

# PHASE 12.1: core, not api.
#
# This import used to reach up into
# backend/app/api/security_headers.py, which made a
# service depend on the API layer -- the only layering
# inversion in the repository, found by
# scripts/verification/audit_repository_structure.py.
#
# The definitions did not change; they moved to a layer
# below both callers.
from backend.app.core.trusted_peers import (
    is_trusted_peer,
    trusted_proxy_networks,
)


# ==========================================================
# IDENTITY ERRORS
# ==========================================================

class ReviewerIdentityError(
    RuntimeError
):

    pass


class ReviewerAuthenticationRequired(
    ReviewerIdentityError
):

    pass


class ReviewerAuthorizationError(
    ReviewerIdentityError
):

    pass


# ==========================================================
# REVIEWER IDENTITY
# ==========================================================

@dataclass(
    frozen=True
)
class ReviewerIdentity:

    reviewer_id: str

    role: str

    source: str


    def to_dict(
        self,
    ) -> dict:

        return {
            "reviewer_id":
                self.reviewer_id,

            "role":
                self.role,

            "source":
                self.source,
        }


# ==========================================================
# REVIEWER IDENTITY SERVICE
# PHASE 7C.5
# ==========================================================

class ReviewerIdentityService:

    # ======================================================
    # MODES
    # ======================================================

    MODE_LOCAL_ENV = (
        "local_env"
    )

    MODE_TRUSTED_HEADERS = (
        "trusted_headers"
    )


    ALLOWED_MODES = {
        MODE_LOCAL_ENV,
        MODE_TRUSTED_HEADERS,
    }


    # ======================================================
    # ROLES
    # ======================================================

    ROLE_VIEWER = (
        "VIEWER"
    )

    ROLE_REVIEWER = (
        "REVIEWER"
    )

    ROLE_ADMIN = (
        "ADMIN"
    )


    ALLOWED_ROLES = {
        ROLE_VIEWER,
        ROLE_REVIEWER,
        ROLE_ADMIN,
    }


    REVIEW_WRITE_ROLES = {
        ROLE_REVIEWER,
        ROLE_ADMIN,
    }


    # ======================================================
    # TRUSTED HEADER NAMES
    # ======================================================

    REVIEWER_ID_HEADER = (
        "X-VIGILOX-REVIEWER-ID"
    )

    REVIEWER_ROLE_HEADER = (
        "X-VIGILOX-REVIEWER-ROLE"
    )


    # ======================================================
    # INITIALIZATION
    # ======================================================

    def __init__(
        self,
        *,
        mode: str | None = None,
        local_reviewer_id: str | None = None,
        trusted_proxies=None,
        local_reviewer_role: str | None = None,
    ):

        resolved_mode = (
            mode
            if mode is not None
            else getenv(
                "VIGILOX_REVIEW_IDENTITY_MODE",
                self.MODE_LOCAL_ENV,
            )
        )


        resolved_mode = (
            str(
                resolved_mode
            )
            .strip()
            .lower()
        )


        if (
            resolved_mode
            not in self.ALLOWED_MODES
        ):

            raise ValueError(
                (
                    "Unsupported reviewer "
                    "identity mode: "
                    f"{resolved_mode}. "
                    "Allowed modes are "
                    "local_env and "
                    "trusted_headers."
                )
            )


        self.mode = (
            resolved_mode
        )


        # ==================================================
        # LOCAL DEVELOPMENT IDENTITY
        # ==================================================

        # PHASE 11.5. Which peers may forward an identity.
        #
        # None means read VIGILOX_TRUSTED_PROXIES, which is
        # what a running deployment does.
        #
        # An explicit value is for a caller that is NOT a
        # deployment: a test of header parsing states the peer
        # it is standing in for, rather than the result
        # depending on the environment it happens to run in.
        self.trusted_proxies = (
            tuple(
                trusted_proxies
            )
            if trusted_proxies is not None
            else None
        )

        self.local_reviewer_id = (
            local_reviewer_id

            if local_reviewer_id
            is not None

            else getenv(
                "VIGILOX_LOCAL_REVIEWER_ID"
            )
        )


        self.local_reviewer_role = (
            local_reviewer_role

            if local_reviewer_role
            is not None

            else getenv(
                "VIGILOX_LOCAL_REVIEWER_ROLE",
                self.ROLE_REVIEWER,
            )
        )


    # ======================================================
    # CASE-INSENSITIVE HEADER LOOKUP
    # ======================================================

    def _get_header(
        self,
        headers: Mapping[
            str,
            str
        ],
        header_name: str,
    ) -> str | None:

        normalized_target = (
            header_name
            .strip()
            .lower()
        )


        for (
            key,
            value,
        ) in headers.items():

            if (
                str(
                    key
                )
                .strip()
                .lower()
                == normalized_target
            ):

                return (
                    str(
                        value
                    )
                )


        return None


    # ======================================================
    # VALIDATE IDENTITY
    # ======================================================

    def _validate_identity(
        self,
        *,
        reviewer_id: str | None,
        role: str | None,
        source: str,
    ) -> ReviewerIdentity:

        normalized_reviewer_id = (
            str(
                reviewer_id
            )
            .strip()

            if reviewer_id
            is not None

            else ""
        )


        if (
            not normalized_reviewer_id
        ):

            raise ReviewerAuthenticationRequired(
                (
                    "Reviewer identity "
                    "is not available."
                )
            )


        if (
            len(
                normalized_reviewer_id
            )
            > 100
        ):

            raise ReviewerAuthenticationRequired(
                (
                    "Reviewer identity exceeds "
                    "the maximum supported "
                    "length."
                )
            )


        normalized_role = (
            str(
                role
            )
            .strip()
            .upper()

            if role
            is not None

            else ""
        )


        if (
            not normalized_role
        ):

            raise ReviewerAuthorizationError(
                (
                    "Reviewer role "
                    "is not available."
                )
            )


        if (
            normalized_role
            not in self.ALLOWED_ROLES
        ):

            raise ReviewerAuthorizationError(
                (
                    "Unsupported reviewer role: "
                    f"{normalized_role}."
                )
            )


        return ReviewerIdentity(
            reviewer_id=(
                normalized_reviewer_id
            ),

            role=(
                normalized_role
            ),

            source=(
                source
            ),
        )


    # ======================================================
    # RESOLVE LOCAL ENV IDENTITY
    # ======================================================

    def _resolve_local_identity(
        self,
    ) -> ReviewerIdentity:

        return (
            self._validate_identity(
                reviewer_id=(
                    self.local_reviewer_id
                ),

                role=(
                    self.local_reviewer_role
                ),

                source=(
                    "LOCAL_ENV"
                ),
            )
        )


    # ======================================================
    # RESOLVE TRUSTED HEADER IDENTITY
    # ======================================================

    def _resolve_trusted_header_identity(
        self,
        headers: Mapping[
            str,
            str
        ],
    ) -> ReviewerIdentity:

        reviewer_id = (
            self._get_header(
                headers,
                self.REVIEWER_ID_HEADER,
            )
        )


        reviewer_role = (
            self._get_header(
                headers,
                self.REVIEWER_ROLE_HEADER,
            )
        )


        return (
            self._validate_identity(
                reviewer_id=(
                    reviewer_id
                ),

                role=(
                    reviewer_role
                ),

                source=(
                    "TRUSTED_HEADER"
                ),
            )
        )


    # ======================================================
    # RESOLVE IDENTITY
    # ======================================================

    def resolve(
        self,
        *,
        headers: (
            Mapping[
                str,
                str
            ]
            | None
        ) = None,
        peer: str | None = None,
    ) -> ReviewerIdentity:

        """
        peer
        ------------------------------------------------------
        PHASE 11.5. The address the request actually arrived
        from.

        In trusted_headers mode the reviewer identity comes
        from an HTTP header, and an HTTP header can be sent by
        anyone who can reach the port. Before Phase 11.5 that
        was the whole check: any client able to reach the
        application directly could send

            X-VIGILOX-REVIEWER-ID: whoever
            X-VIGILOX-REVIEWER-ROLE: ADMIN

        and be that reviewer, with their decisions written into
        the audit trail under that name.

        The documented mitigation was that the reverse proxy
        strips client-supplied copies. That is necessary and it
        is not sufficient: it assumes the proxy is the only
        path to the port. A container published on the host, a
        misconfigured security group, or anything else inside
        the network reaches the application directly and the
        proxy never sees it.

        So the headers are now honoured only when the peer is
        one of VIGILOX_TRUSTED_PROXIES. With that unset,
        NOTHING is trusted -- a deployment that forgot to
        configure it gets refused identity rather than
        accepting it from anywhere.
        """

        # ==================================================
        # LOCAL SERVER-CONFIGURED IDENTITY
        # ==================================================

        if (
            self.mode
            == self.MODE_LOCAL_ENV
        ):

            return (
                self._resolve_local_identity()
            )


        # ==================================================
        # TRUSTED UPSTREAM IDENTITY
        # ==================================================

        if (
            self.mode
            == self.MODE_TRUSTED_HEADERS
        ):

            if headers is None:

                raise (
                    ReviewerAuthenticationRequired(
                        (
                            "Trusted reviewer "
                            "headers are required."
                        )
                    )
                )


            # ----------------------------------------------
            # THE HEADERS ARE ONLY TRUSTED FROM A PROXY
            # ----------------------------------------------
            # Deliberately the same error as a missing
            # identity. Telling an untrusted caller that its
            # headers were rejected for coming from the wrong
            # address confirms both that the mechanism exists
            # and which header names to try from somewhere
            # else.
            # ----------------------------------------------

            if not is_trusted_peer(
                peer,
                self.trusted_proxies,
            ):

                raise (
                    ReviewerAuthenticationRequired(
                        (
                            "Trusted reviewer "
                            "headers are required."
                        )
                    )
                )


            return (
                self._resolve_trusted_header_identity(
                    headers
                )
            )


        # ==================================================
        # DEFENSIVE STATE CHECK
        # ==================================================

        raise RuntimeError(
            (
                "Reviewer identity service "
                "entered an unsupported mode."
            )
        )


    # ======================================================
    # REVIEW AUTHORIZATION
    # ======================================================

    def require_review_access(
        self,
        identity: ReviewerIdentity,
    ) -> ReviewerIdentity:

        if (
            identity.role
            not in self.REVIEW_WRITE_ROLES
        ):

            raise ReviewerAuthorizationError(
                (
                    "Reviewer does not have "
                    "permission to submit "
                    "human review decisions."
                )
            )


        return identity


    # ======================================================
    # RESOLVE + AUTHORIZE REVIEWER
    # ======================================================

    # ======================================================
    # DEPLOYMENT POSTURE
    # PHASE 11.5
    # ======================================================

    def posture_errors(
        self,
        *,
        environment: str,
    ) -> list[str]:

        """
        Reasons this identity configuration must not serve
        production traffic.

        Returns a list so a misconfigured deployment learns
        everything wrong with it at once rather than one
        restart at a time.

        Called at startup. Refusing to start is the point: a
        service that comes up and quietly attributes every
        review to "local-reviewer" is worse than one that
        does not come up, because the first is discovered by
        auditing decisions after the fact.
        """

        if environment != "production":
            return []

        problems = []

        if self.mode == self.MODE_LOCAL_ENV:

            problems.append(
                "VIGILOX_REVIEW_IDENTITY_MODE is "
                "'local_env', which takes the reviewer from "
                "server configuration and gives every "
                "reviewer the same identity. Every review "
                "decision would be attributed to "
                f"'{self.local_reviewer_id}' in the audit "
                "trail. Production requires "
                "'trusted_headers' behind an authenticating "
                "proxy."
            )

        if self.mode == self.MODE_TRUSTED_HEADERS:

            configured = (
                self.trusted_proxies
                if self.trusted_proxies is not None
                else trusted_proxy_networks()
            )

            if not configured:

                problems.append(
                    "VIGILOX_REVIEW_IDENTITY_MODE is "
                    "'trusted_headers' but "
                    "VIGILOX_TRUSTED_PROXIES is empty. The "
                    "reviewer identity would come from an "
                    "HTTP header that any client able to "
                    "reach this port could send, including "
                    "role=ADMIN. Set it to the address or "
                    "CIDR of the reverse proxy."
                )

        return problems


    def resolve_reviewer(
        self,
        *,
        headers: (
            Mapping[
                str,
                str
            ]
            | None
        ) = None,
        peer: str | None = None,
    ) -> ReviewerIdentity:

        identity = (
            self.resolve(
                headers=(
                    headers
                ),
                peer=(
                    peer
                ),
            )
        )


        return (
            self.require_review_access(
                identity
            )
        )