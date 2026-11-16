# Grader-only source authority, v1

This directory is mounted only into the isolated verifier. It contains the native SI PDF and the original ESI ZIP for DOI 10.1039/D0SC04896H. The candidate environment receives no file from this directory. Candidate-acquired copies are matched by original bytes and row values in `case06_source_authority.py`.

Native SI PDF: `SC-012-D0SC04896H-s001.pdf`, SHA-256 `ec3744548892430c8c32c6c520eb06e6820638bdf4c6ea33c686e6f8cf3b6a43`.
Native ESI ZIP: `SC-012-D0SC04896H-s002.zip`, SHA-256 `ce339248e5d4db6c3939624d08e5a7fdf8a83bcff8f3ddb0543721638641aa8e`.
Registered member: `SC-012-D0SC04896H-s050.csv`; protected adapter independently validates its bytes against the extracted local mirror hash and parsed native headers/rows.

The authority authenticates correspondence to published SI bytes only. It does not validate the underlying primary experiments or scientific truth.
