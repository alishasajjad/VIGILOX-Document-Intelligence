import ipaddress
import os


# ==========================================================
# WHICH PEERS MAY BE BELIEVED
# PHASE 12.1
# ==========================================================
#
# Moved here from backend/app/api/security_headers.py, and the
# move is the point.
#
# The 11.5 identity fix made ReviewerIdentityService -- a
# SERVICE -- import from backend/app/api/. That is a layering
# inversion: the API layer is allowed to depend on services,
# not the other way round, and the 12.1 structure audit caught
# it as the only one in the repository.
#
# It was not a naming problem. Asking "is this peer trusted"
# is not an HTTP question at all: it is a question about the
# network the process is running in, and both the API
# middleware and the identity service need the answer. So it
# belongs below both of them, which is here in core/ -- the
# same place logging and timing live.
#
# security_headers.py re-exports these names, so every
# existing caller and test keeps working.
#
#
# WHY LITERALS EXIST ALONGSIDE NETWORKS
# ----------------------------------------------------------
# Not every peer is an IP address. A unix domain socket has no
# address, and a test client reports the host "testclient".
# A literal only ever matches itself, so it cannot widen trust
# the way a mis-parsed CIDR could -- and a hostname put in the
# list by mistake simply never matches, which is the safe
# direction.
# ==========================================================


def parse_trusted_proxies(
    entries,
) -> tuple[tuple, tuple[str, ...]]:

    """
    Split configuration into IP networks and literal peers.

    Returns (networks, literals).

    An address or CIDR becomes a network. Anything else is
    kept as a LITERAL exact-match peer, because not every peer
    is an IP address:

        a unix domain socket has no address at all
        a test client reports the host "testclient"

    A literal only ever matches itself, so keeping it cannot
    widen trust the way a mis-parsed CIDR could. A hostname
    put here by mistake simply never matches, which is the
    safe direction.
    """

    networks = []
    literals = []

    for entry in entries:

        candidate = str(
            entry
        ).strip()

        if not candidate:
            continue

        try:
            networks.append(
                ipaddress.ip_network(
                    candidate,
                    strict=False,
                )
            )

        except ValueError:
            literals.append(
                candidate
            )

    return (
        tuple(
            networks
        ),
        tuple(
            literals
        ),
    )


def trusted_proxy_networks() -> tuple:

    """
    Peers whose forwarded identity headers may be trusted,
    from VIGILOX_TRUSTED_PROXIES.

    Returns the combined configuration as one tuple, so an
    empty result means "nothing configured" for any caller
    that only needs to know whether the list is set at all --
    which is what the production posture check asks.
    """

    raw = os.getenv(
        "VIGILOX_TRUSTED_PROXIES",
        "",
    ).strip()

    if not raw:
        return ()

    networks, literals = parse_trusted_proxies(
        raw.split(
            ","
        )
    )

    return networks + literals


def is_trusted_peer(
    client_host: str | None,
    configured=None,
) -> bool:

    """
    Whether this request arrived from a trusted proxy.

    configured
    ------------------------------------------------------
    An explicit iterable of addresses, CIDRs or literal
    peers. When omitted, VIGILOX_TRUSTED_PROXIES is read.

    Passing it explicitly is how a caller that is not a
    deployment -- a unit test of header parsing, say -- states
    which peer it is standing in for, instead of the answer
    depending on the environment the test happens to run in.

    Nothing configured means nothing is trusted. That is the
    safe direction: a deployment that forgot to configure the
    list refuses identity headers rather than accepting them
    from anyone.
    """

    if configured is None:

        raw = os.getenv(
            "VIGILOX_TRUSTED_PROXIES",
            "",
        ).strip()

        entries = (
            raw.split(
                ","
            )
            if raw
            else ()
        )

    else:
        entries = configured

    networks, literals = parse_trusted_proxies(
        entries
    )

    if not networks and not literals:
        return False

    if not client_host:
        return False

    if client_host in literals:
        return True

    try:
        address = ipaddress.ip_address(
            client_host
        )

    except ValueError:
        return False

    return any(
        address in network
        for network in networks
    )
