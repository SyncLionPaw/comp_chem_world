#!/usr/bin/env python3
"""Allow no NPT warning or only GROMACS's expected Berendsen warning."""
import argparse
import re
from pathlib import Path


def validate(text: str) -> tuple[bool, str]:
    lines = text.splitlines()
    warning_lines = [(i, line) for i, line in enumerate(lines)
                     if re.match(r"^\s*WARNING\b.*$", line, re.I)]
    summaries = []
    for line in lines:
        m = re.match(r"^\s*There\s+(?:was|were)\s+(\d+)\s+warnings?\s*$", line, re.I)
        if m:
            summaries.append(int(m.group(1)))
    # Successful grompp normally omits the summary when there are no warnings.
    # The shell caller has already checked grompp's exit code.
    if not summaries and not warning_lines:
        return True, "no grompp warning headers or warning summary"
    if len(summaries) != 1:
        return False, f"missing or ambiguous grompp warning count summary: {summaries}"
    reported = summaries[0]
    if not warning_lines:
        if reported == 0:
            return True, "no grompp warnings"
        return False, f"grompp reported {reported} warning(s) without warning headers"
    if reported != len(warning_lines):
        return False, f"warning header count {len(warning_lines)} differs from grompp summary {reported}"
    if len(warning_lines) != 1 or reported != 1:
        return False, f"unexpected NPT grompp warning headers: {[line for _, line in warning_lines]}"
    idx, header = warning_lines[0]
    if not re.fullmatch(r"\s*WARNING\s+1\s+\[file npt\.mdp\]:\s*", header):
        return False, f"unrecognized NPT grompp warning header: {header.strip()}"
    end = next((j for j in range(idx + 1, len(lines))
                if re.match(r"^\s*There\s+(?:was|were)\s+\d+\s+warnings?\s*$", lines[j], re.I)), len(lines))
    body = "\n".join(lines[idx + 1:end])
    if "The Berendsen barostat does not generate any strictly correct ensemble" not in body:
        return False, "NPT warning is not the documented Berendsen barostat warning"
    return True, "single documented Berendsen barostat warning"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("log", type=Path)
    a = p.parse_args()
    ok, message = validate(a.log.read_text(errors="replace"))
    print(message)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
