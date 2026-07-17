# SPDX-License-Identifier: Apache-2.0

"""Golden-file comparator for the SONiC config-generation E2E test.

Compares exported SONiC ``config_db.json`` files against committed golden
files. config_db is a shallow TABLE -> entry -> attribute tree, so
structural difference paths are rendered as ``TABLE|entry.attribute``.

Canonicalization sorts dictionary keys only; array order is preserved and
compared, since list order can be part of the generated contract.
"""

import argparse
import difflib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _walk(golden, actual, path, depth, out):
    """Collect difference paths between two parsed JSON values.

    ``depth`` counts dict levels already entered: children of the top level
    (tables) attach with ``|``, everything deeper with ``.``. List indices
    attach as ``[i]`` and stay at their parent's depth.
    """
    if isinstance(golden, dict) and isinstance(actual, dict):
        for key in sorted(golden.keys() | actual.keys()):
            sep = "|" if depth == 1 else "."
            child = f"{path}{sep}{key}" if path else str(key)
            if key not in actual:
                out.append(f"{child}: only in golden")
            elif key not in golden:
                out.append(f"{child}: only in actual")
            else:
                _walk(golden[key], actual[key], child, depth + 1, out)
    elif isinstance(golden, list) and isinstance(actual, list):
        for i in range(max(len(golden), len(actual))):
            child = f"{path}[{i}]"
            if i >= len(actual):
                out.append(f"{child}: only in golden")
            elif i >= len(golden):
                out.append(f"{child}: only in actual")
            else:
                _walk(golden[i], actual[i], child, depth, out)
    elif golden != actual:
        out.append(f"{path}: golden {golden!r}, actual {actual!r}")


def diff_paths(golden, actual):
    """Return sorted structural paths of the differences between two configs."""
    out = []
    _walk(golden, actual, "", 0, out)
    return sorted(out)


def _canonical(config):
    """Canonical JSON text: dict keys sorted, arrays untouched."""
    return json.dumps(config, indent=2, sort_keys=True) + "\n"


def unified_diff(golden, actual, name):
    """Unified diff of the canonicalized golden and actual configs."""
    return "".join(
        difflib.unified_diff(
            _canonical(golden).splitlines(keepends=True),
            _canonical(actual).splitlines(keepends=True),
            fromfile=f"golden/{name}",
            tofile=f"export/{name}",
        )
    )


@dataclass
class Mismatch:
    """Content difference of one exported file against its golden file."""

    paths: list
    diff: str


@dataclass
class CompareResult:
    """Outcome of comparing an export directory against the golden directory."""

    missing: list = field(default_factory=list)
    extra: list = field(default_factory=list)
    mismatched: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not (self.missing or self.extra or self.mismatched)

    def report(self):
        lines = []
        for name in self.missing:
            lines.append(
                f"MISSING {name}: not exported "
                "(generation or export failed - see generate log)"
            )
        for name in self.extra:
            lines.append(f"EXTRA {name}: unexpected extra export (no golden file)")
        for name, mismatch in self.mismatched.items():
            lines.append(f"MISMATCH {name}:")
            lines.extend(f"  {path}" for path in mismatch.paths)
            lines.append(mismatch.diff)
        if not lines:
            lines.append("OK: exports match the golden files")
        return "\n".join(lines)


def compare_dirs(golden_dir, export_dir):
    """Compare all golden ``*.json`` files against the exported ones.

    Requires exact file-set equality: a golden file without an export is
    ``missing`` (generation or export failed), an export without a golden
    file is ``extra``, and differing content is ``mismatched``. Non-JSON
    files (e.g. firmware symlinks in the export directory) are ignored.
    """
    golden_dir = Path(golden_dir)
    export_dir = Path(export_dir)
    golden_names = {p.name for p in golden_dir.glob("*.json")}
    export_names = {p.name for p in export_dir.glob("*.json")}

    result = CompareResult(
        missing=sorted(golden_names - export_names),
        extra=sorted(export_names - golden_names),
    )
    for name in sorted(golden_names & export_names):
        golden = json.loads((golden_dir / name).read_text())
        actual = json.loads((export_dir / name).read_text())
        paths = diff_paths(golden, actual)
        if paths:
            result.mismatched[name] = Mismatch(
                paths=paths, diff=unified_diff(golden, actual, name)
            )
    return result


def regenerate(golden_dir, export_dir):
    """Rewrite the golden directory from the export directory.

    Every exported ``*.json`` file is stored in canonical form (sorted dict
    keys) so regenerated goldens produce minimal, reviewable git diffs;
    stale golden files without a matching export are removed. Never run in
    CI - regeneration is a deliberate local step after an intentional
    generator change.
    """
    golden_dir = Path(golden_dir)
    export_dir = Path(export_dir)
    golden_dir.mkdir(parents=True, exist_ok=True)

    export_names = {p.name for p in export_dir.glob("*.json")}
    for stale in golden_dir.glob("*.json"):
        if stale.name not in export_names:
            stale.unlink()
    for name in sorted(export_names):
        config = json.loads((export_dir / name).read_text())
        (golden_dir / name).write_text(_canonical(config))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", required=True, help="golden file directory")
    parser.add_argument("--export", required=True, help="export directory to check")
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="rewrite the golden files from the export directory",
    )
    args = parser.parse_args(argv)

    if args.regenerate:
        regenerate(args.golden, args.export)
        return 0

    result = compare_dirs(args.golden, args.export)
    print(result.report())
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
