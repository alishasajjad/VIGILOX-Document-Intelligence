"""
==========================================================
REPOSITORY STRUCTURE AUDIT
PHASE 11.1
==========================================================

WHAT THIS ANSWERS
----------------------------------------------------------
Four questions, before anything is packaged for deployment:

  1. LAYERING
     Does the import graph still run one way? Which edges
     cross a boundary, and is each crossing one the
     architecture doc actually permits?

  2. REACHABILITY
     Is every production module reachable from an
     entrypoint? A module nothing imports is either dead or
     a missing wire, and the two look identical from
     outside.

  3. PUBLIC SURFACE
     Which definitions does each module export that nothing
     else uses? Not a delete list -- a list to read.

  4. WHAT SHIPS
     Which paths are source, which are runtime data, and
     which are generated. A deployment package that
     includes runtime data or evaluation ground truth is a
     data leak, not a packaging mistake.


WHY THIS IS A REPORT AND NOT A DELETE SCRIPT
----------------------------------------------------------
Static reachability cannot see a module loaded by name, a
route registered by decorator, a fixture found by
convention, or a fail-safe that exists precisely because
nothing has needed it yet.

So this prints findings and exits 0 unless it finds
something that is unambiguously wrong -- a layering
inversion, or a source file inside a runtime data
directory. Everything else is for a person to read.

Removing code on the strength of an unread report is how a
cleanup becomes an outage.
"""

import ast
import collections
import json
import sys

from pathlib import Path


PROJECT_ROOT = (
    Path(
        __file__
    )
    .resolve()
    .parents[2]
)


# ==========================================================
# WHAT COUNTS AS WHAT
# ==========================================================

# Production Python. Everything that would be deployed.
SOURCE_ROOTS = (
    "backend",
    "database",
)


# Executed by a person or a scheduler, never imported.
ENTRYPOINT_ROOTS = (
    "scripts",
    "tests",
)


# Runtime business data. Never source, never packaged.
RUNTIME_DATA = (
    "storage",
)


# Generated artifacts. Reproducible, never packaged.
GENERATED = (
    "output",
)


# Deliberately versioned project artifacts.
VERSIONED_ARTIFACTS = (
    "evaluation",
)


# Local, unversioned, and not to be packaged for the reason
# recorded in .gitignore.
EXCLUDED_FROM_PACKAGE = (
    "samples",
    ".venv",
    ".git",
    "storage",
    "output",
    "evaluation",
)


# ==========================================================
# LAYERS
# ==========================================================
#
# Lower numbers may be imported by higher ones. An import in
# the other direction is an inversion.
#
# core/ and domain/ are CROSS-CUTTING: they carry the
# extraction schema, the job state machine, the
# classification and duplicate rules, and finding
# normalization. They perform no I/O and depend on nothing
# above them, so any layer may import them. That exemption
# is what makes the two
# database -> backend.app.domain.job_states edges legitimate
# rather than inversions -- see docs/architecture/overview.md.
# ==========================================================

LAYERS = {
    "database": 1,
    "backend/app/services": 2,
    "backend/app/api": 3,
    "backend/app/main.py": 4,
}


CROSS_CUTTING = (
    "backend/app/core",
    "backend/app/domain",
)


def bucket_of_module(
    module: str,
) -> str | None:

    """Which layer a dotted module name belongs to."""

    table = (
        (
            "backend.app.services",
            "backend/app/services",
        ),
        (
            "backend.app.domain",
            "backend/app/domain",
        ),
        (
            "backend.app.core",
            "backend/app/core",
        ),
        (
            "backend.app.api",
            "backend/app/api",
        ),
        (
            "backend.app.main",
            "backend/app/main.py",
        ),
        (
            "database",
            "database",
        ),
    )

    for prefix, name in table:

        if (
            module == prefix
            or module.startswith(
                prefix
                + "."
            )
        ):
            return name

    return None


def bucket_of_path(
    relative: Path,
) -> str | None:

    """Which layer a file belongs to."""

    text = relative.as_posix()

    if text == "backend/app/main.py":
        return "backend/app/main.py"

    for name in (
        "backend/app/services",
        "backend/app/domain",
        "backend/app/core",
        "backend/app/api",
    ):

        if text.startswith(
            name
            + "/"
        ):
            return name

    if text.startswith(
        "database/"
    ):
        return "database"

    return None


# ==========================================================
# READING THE SOURCE
# ==========================================================

def python_files(
    root: str,
) -> list[Path]:

    base = (
        PROJECT_ROOT
        / root
    )

    if not base.exists():
        return []

    return [
        path
        for path in sorted(
            base.rglob(
                "*.py"
            )
        )
        if "__pycache__" not in path.parts
    ]


def module_name(
    relative: Path,
) -> str:

    parts = list(
        relative.with_suffix(
            ""
        ).parts
    )

    if parts and parts[-1] == "__init__":
        parts.pop()

    return ".".join(
        parts
    )


def imports_of(
    tree: ast.AST,
) -> list[str]:

    found = []

    for node in ast.walk(
        tree
    ):

        if (
            isinstance(
                node,
                ast.ImportFrom,
            )
            and node.module
        ):
            found.append(
                node.module
            )

        elif isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                found.append(
                    alias.name
                )

    return found


def definitions_of(
    tree: ast.AST,
) -> list[str]:

    """Top-level names a module offers to other modules."""

    names = []

    for node in tree.body:

        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):

            if not node.name.startswith(
                "_"
            ):
                names.append(
                    node.name
                )

        elif isinstance(
            node,
            ast.Assign,
        ):

            for target in node.targets:

                if (
                    isinstance(
                        target,
                        ast.Name,
                    )
                    and not target.id.startswith(
                        "_"
                    )
                    and target.id.isupper()
                ):
                    names.append(
                        target.id
                    )

    return names


# ==========================================================
# THE AUDIT
# ==========================================================

def main() -> int:

    print(
        "=" * 74
    )
    print(
        "PHASE 11.1 - REPOSITORY STRUCTURE AUDIT"
    )
    print(
        "=" * 74
    )

    problems: list[str] = []


    # ------------------------------------------------------
    # COLLECT
    # ------------------------------------------------------

    source_modules: dict[str, Path] = {}

    trees: dict[str, ast.AST] = {}

    for root in SOURCE_ROOTS:

        for path in python_files(
            root
        ):

            relative = path.relative_to(
                PROJECT_ROOT
            )

            name = module_name(
                relative
            )

            source_modules[name] = relative

            trees[name] = ast.parse(
                path.read_text(
                    encoding="utf-8"
                )
            )


    entry_trees: dict[str, ast.AST] = {}

    for root in ENTRYPOINT_ROOTS:

        for path in python_files(
            root
        ):

            relative = path.relative_to(
                PROJECT_ROOT
            )

            entry_trees[
                relative.as_posix()
            ] = ast.parse(
                path.read_text(
                    encoding="utf-8"
                )
            )


    print()
    print(
        f"{len(source_modules)} production modules, "
        f"{len(entry_trees)} entrypoint files"
    )


    # ------------------------------------------------------
    # 1. LAYERING
    # ------------------------------------------------------

    print()
    print(
        "-" * 74
    )
    print(
        "1. LAYERING"
    )
    print(
        "-" * 74
    )

    edges = collections.Counter()

    inversions: list[str] = []

    cross_cutting_edges: list[str] = []

    for name, tree in trees.items():

        source_bucket = bucket_of_path(
            source_modules[name]
        )

        if source_bucket is None:
            continue

        for imported in imports_of(
            tree
        ):

            target_bucket = bucket_of_module(
                imported
            )

            if (
                target_bucket is None
                or target_bucket == source_bucket
            ):
                continue

            edges[
                (
                    source_bucket,
                    target_bucket,
                )
            ] += 1

            # Cross-cutting is always allowed and is recorded
            # rather than judged.
            if target_bucket in CROSS_CUTTING:

                if source_bucket not in CROSS_CUTTING:
                    cross_cutting_edges.append(
                        f"{source_modules[name].as_posix()}"
                        f" -> {imported}"
                    )

                continue

            source_rank = LAYERS.get(
                source_bucket
            )

            target_rank = LAYERS.get(
                target_bucket
            )

            if (
                source_rank is not None
                and target_rank is not None
                and target_rank > source_rank
            ):
                inversions.append(
                    f"{source_modules[name].as_posix()}"
                    f" -> {imported}"
                    f"  ({source_bucket} imports upward "
                    f"into {target_bucket})"
                )

    for (
        source_bucket,
        target_bucket,
    ), count in sorted(
        edges.items(),
        key=lambda item: -item[1],
    ):
        print(
            f"   {source_bucket:22s} -> "
            f"{target_bucket:22s} {count}"
        )

    print()

    if inversions:

        print(
            f"   [FAIL] {len(inversions)} layering "
            f"inversion(s):"
        )

        for line in inversions:
            print(
                f"          {line}"
            )

        problems.append(
            f"{len(inversions)} layering inversion(s)"
        )

    else:
        print(
            "   [OK] no layering inversions"
        )

    if cross_cutting_edges:

        print()
        print(
            f"   {len(cross_cutting_edges)} cross-cutting "
            f"import(s) into core/ or domain/, which the "
            f"architecture permits:"
        )

        # The ones worth reading are the edges from a LOWER
        # layer, because those are what a strict one-way rule
        # would call an inversion.
        upward = [
            line
            for line in cross_cutting_edges
            if line.startswith(
                "database/"
            )
        ]

        for line in upward:
            print(
                f"          {line}"
            )

        if not upward:
            print(
                "          (none from database/)"
            )


    # ------------------------------------------------------
    # 2. REACHABILITY
    # ------------------------------------------------------

    print()
    print(
        "-" * 74
    )
    print(
        "2. REACHABILITY"
    )
    print(
        "-" * 74
    )

    imported_by: dict[
        str,
        set[str]
    ] = {
        name: set()
        for name in source_modules
    }

    def record(
        importer: str,
        tree: ast.AST,
    ) -> None:

        for imported in imports_of(
            tree
        ):

            for name in source_modules:

                if (
                    imported == name
                    or imported.startswith(
                        name
                        + "."
                    )
                ):
                    imported_by[name].add(
                        importer
                    )

    for name, tree in trees.items():
        record(
            source_modules[name].as_posix(),
            tree,
        )

    for label, tree in entry_trees.items():
        record(
            label,
            tree,
        )

    unreferenced = sorted(
        source_modules[name].as_posix()
        for name, importers in imported_by.items()
        if not importers
        and not source_modules[
            name
        ].name.startswith(
            "__init__"
        )
    )

    production_only = sorted(
        source_modules[name].as_posix()
        for name, importers in imported_by.items()
        if importers
        and not any(
            importer.startswith(
                (
                    "backend/",
                    "database/",
                )
            )
            for importer in importers
        )
        and not source_modules[
            name
        ].name.startswith(
            "__init__"
        )
    )

    if unreferenced:

        print(
            f"   {len(unreferenced)} module(s) imported by "
            f"nothing at all -- READ, do not delete:"
        )

        for line in unreferenced:
            print(
                f"          {line}"
            )

    else:
        print(
            "   [OK] every production module is imported "
            "somewhere"
        )

    if production_only:

        print()
        print(
            f"   {len(production_only)} module(s) imported "
            f"ONLY by tests or scripts, never by production "
            f"code:"
        )

        for line in production_only:
            print(
                f"          {line}"
            )


    # ------------------------------------------------------
    # 3. UNUSED PUBLIC DEFINITIONS
    # ------------------------------------------------------

    print()
    print(
        "-" * 74
    )
    print(
        "3. PUBLIC DEFINITIONS NOTHING ELSE NAMES"
    )
    print(
        "-" * 74
    )
    print(
        "   Two lists. The first is names used only inside "
        "the file that defines"
    )
    print(
        "   them, which is normal for a nested type or a "
        "neighbouring constant."
    )
    print(
        "   The second is names that appear nowhere else at "
        "all."
    )

    # Every identifier that appears anywhere outside the
    # module that defines it. Textual on purpose: a name used
    # in a getattr, a decorator, a route, an f-string or a
    # test is still used, and an AST walk would miss all of
    # those and produce a confident wrong answer.
    corpus: dict[str, str] = {}

    for root in (
        *SOURCE_ROOTS,
        *ENTRYPOINT_ROOTS,
    ):

        for path in python_files(
            root
        ):
            corpus[
                path.relative_to(
                    PROJECT_ROOT
                ).as_posix()
            ] = path.read_text(
                encoding="utf-8"
            )

    unused: dict[
        str,
        list[str]
    ] = {}

    # Named only inside the file that defines it. Alive, but
    # worth listing separately -- see the note in the loop.
    local_only: dict[
        str,
        list[str]
    ] = {}

    for name, relative in sorted(
        source_modules.items()
    ):

        own = relative.as_posix()

        for definition in definitions_of(
            trees[name]
        ):

            elsewhere = any(
                definition in text
                for path, text in corpus.items()
                if path != own
            )

            if elsewhere:
                continue

            # ----------------------------------------------
            # USED WHERE IT IS DEFINED
            # ----------------------------------------------
            # A name can be unreferenced outside its own file
            # and still be entirely alive: a Pydantic model
            # used only as a nested field type, a constant
            # read by a function beside it, a base class.
            #
            # The first version of this audit reported the six
            # nested response models in
            # backend/app/api/schemas.py as unreferenced --
            # and they are all field types of
            # ReviewQueueResponse, DocumentListResponse and
            # DashboardSummaryResponse, declared three lines
            # further down the same file.
            #
            # That is a misleading report, not a wrong one,
            # and a misleading report in a list nobody can
            # verify quickly is how a live definition gets
            # deleted. So the two cases are separated.
            # ----------------------------------------------

            body = corpus[own]

            # Occurrences beyond the definition itself. The
            # definition line contributes one.
            local_uses = body.count(
                definition
            ) - 1

            if local_uses > 0:
                local_only.setdefault(
                    own,
                    [],
                ).append(
                    f"{definition} "
                    f"(used {local_uses}x in this file)"
                )

                continue

            unused.setdefault(
                own,
                [],
            ).append(
                definition
            )

    if local_only:

        local_total = sum(
            len(
                names
            )
            for names in local_only.values()
        )

        print()
        print(
            f"   USED LOCALLY ONLY -- {local_total} "
            f"definition(s) across {len(local_only)} "
            f"module(s)."
        )
        print(
            "   These are alive. Listed so they are not "
            "mistaken for the list below."
        )
        print()

        for path, names in sorted(
            local_only.items()
        ):
            print(
                f"          {path}"
            )

            for definition in names:
                print(
                    f"              {definition}"
                )

    if unused:

        total = sum(
            len(
                names
            )
            for names in unused.values()
        )

        print()
        print(
            f"   NAMED NOWHERE ELSE -- {total} "
            f"definition(s) across {len(unused)} module(s)."
        )
        print(
            "   This is a list to READ, not a delete list. A "
            "fail-safe, a route handler"
        )
        print(
            "   registered by decorator, a compatibility "
            "shim and genuinely dead code"
        )
        print(
            "   all look identical from here."
        )
        print()

        for path, names in sorted(
            unused.items()
        ):
            print(
                f"          {path}"
            )

            for definition in names:
                print(
                    f"              {definition}"
                )

    if not unused and not local_only:
        print(
            "   [OK] every public definition is named "
            "somewhere else"
        )


    # ------------------------------------------------------
    # 4. WHAT SHIPS
    # ------------------------------------------------------

    print()
    print(
        "-" * 74
    )
    print(
        "4. WHAT SHIPS"
    )
    print(
        "-" * 74
    )

    for label, roots in (
        (
            "source, deployed",
            SOURCE_ROOTS
            + (
                "frontend",
            ),
        ),
        (
            "entrypoints, not imported",
            ENTRYPOINT_ROOTS,
        ),
        (
            "runtime business data, never packaged",
            RUNTIME_DATA,
        ),
        (
            "generated, never packaged",
            GENERATED,
        ),
        (
            "versioned artifacts, not packaged",
            VERSIONED_ARTIFACTS,
        ),
    ):

        counts = []

        for root in roots:

            base = (
                PROJECT_ROOT
                / root
            )

            if not base.exists():
                continue

            files = [
                path
                for path in base.rglob(
                    "*"
                )
                if path.is_file()
                and "__pycache__"
                not in path.parts
            ]

            counts.append(
                f"{root} ({len(files)})"
            )

        print(
            f"   {label:44s} "
            + ", ".join(
                counts
            )
        )


    # ------------------------------------------------------
    # A SOURCE FILE INSIDE RUNTIME DATA IS A REAL PROBLEM
    # ------------------------------------------------------

    stray: list[str] = []

    for root in (
        *RUNTIME_DATA,
        *GENERATED,
    ):

        base = (
            PROJECT_ROOT
            / root
        )

        if not base.exists():
            continue

        for path in base.rglob(
            "*.py"
        ):

            if "__pycache__" in path.parts:
                continue

            stray.append(
                path.relative_to(
                    PROJECT_ROOT
                ).as_posix()
            )

    print()

    if stray:

        print(
            f"   [FAIL] {len(stray)} Python file(s) inside a "
            f"runtime or generated directory:"
        )

        for line in stray:
            print(
                f"          {line}"
            )

        problems.append(
            f"{len(stray)} source file(s) in a runtime or "
            f"generated directory"
        )

    else:
        print(
            "   [OK] no source files inside runtime or "
            "generated directories"
        )


    # ------------------------------------------------------
    # VERDICT
    # ------------------------------------------------------

    report = (
        PROJECT_ROOT
        / "output"
        / "repository_structure_audit.json"
    )

    report.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report.write_text(
        json.dumps(
            {
                "modules": len(
                    source_modules
                ),

                "edges": {
                    f"{a} -> {b}": count
                    for (
                        a,
                        b,
                    ), count in edges.items()
                },

                "inversions": inversions,

                "cross_cutting_from_database": [
                    line
                    for line in cross_cutting_edges
                    if line.startswith(
                        "database/"
                    )
                ],

                "unreferenced_modules": unreferenced,

                "production_unused_modules": (
                    production_only
                ),

                "unused_public_definitions": unused,

                "locally_used_definitions": local_only,

                "stray_source_files": stray,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "=" * 74
    )

    if problems:

        print(
            "[FAIL] STRUCTURE AUDIT FOUND: "
            + "; ".join(
                problems
            )
        )
        print(
            "=" * 74
        )

        return 1

    print(
        "[PASS] STRUCTURE AUDIT FOUND NOTHING "
        "UNAMBIGUOUSLY WRONG"
    )
    print(
        f"       report: "
        f"{report.relative_to(PROJECT_ROOT).as_posix()}"
    )
    print(
        "       the reachability and public-definition "
        "lists above are for a person to read"
    )
    print(
        "=" * 74
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
