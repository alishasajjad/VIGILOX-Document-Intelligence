from dataclasses import (
    dataclass,
)

from os import (
    getenv,
)

from typing import (
    Mapping,
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
    ) -> ReviewerIdentity:

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
    ) -> ReviewerIdentity:

        identity = (
            self.resolve(
                headers=(
                    headers
                )
            )
        )


        return (
            self.require_review_access(
                identity
            )
        )