"""Focused static parsing tests; candidate shell and helper source are never executed."""
from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("case04_verify_parser_under_test", HERE / "verify.py")
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)

QMAP = (
    "python3 make-lambda-input.py --structure scf.in --elph-dir elph_dir "
    "--nq1 4 --nq2 4 --nq3 1 --emax 30.0 --degauss 0.12 "
    "--ngauss 0 --mu 0.16 0.10"
)
STAGES = (
    '"$PW" < scf.in > scf.out',
    '"$PW" < coarse_scf.in > coarse_scf.out',
    '"$PH" < ph.in > ph.out',
    '"$Q2R" < q2r.in > q2r.out',
    '"$MATDYN" < matdyn.in > matdyn.out',
    QMAP,
    '"$LAMBDA" < lambda_mu016.in > lambda_mu016.out',
    '"$LAMBDA" < lambda_mu010.in > lambda_mu010.out',
)
EXPECTED = ["dense", "coarse", "ph", "q2r", "matdyn", "qmap", "mu016", "mu010"]


def script(assignments, commands=STAGES):
    return "\n".join([*assignments, *commands]) + "\n"


def names(text):
    return [name for name, _ in verify._resolve_run_stages(text)]


class RunStageParserTests(unittest.TestCase):
    def test_historical_shape_is_recognized_without_execution(self):
        assignments = [f'{name}="${{{name}:-{value}}}"' for name, value in
                       (("PW", "pw.x"), ("PH", "ph.x"), ("Q2R", "q2r.x"),
                        ("MATDYN", "matdyn.x"), ("LAMBDA", "lambda.x"),
                        ("PYTHON", "python3"))]
        continued_qmap = QMAP.replace(" --", " " + chr(92) + "\n  --") + " # valid continued helper invocation"
        commands = list(STAGES)
        commands[5] = continued_qmap
        self.assertEqual(names(script(assignments, commands)), EXPECTED)

    def test_double_quoted_self_defaults_resolve_all_stages(self):
        assignments = [f'{name}="${{{name}:-{value}}}"' for name, value in
                       (("PW", "pw.x"), ("PH", "ph.x"), ("Q2R", "q2r.x"),
                        ("MATDYN", "matdyn.x"), ("LAMBDA", "lambda.x"), ("PYTHON", "python3"))]
        self.assertEqual(names(script(assignments)), EXPECTED)

    def test_unquoted_self_defaults_and_quoted_literal_assignments_resolve(self):
        assignments = ["PW=${PW:-pw.x}", "PH='ph.x'", 'Q2R="q2r.x"', "MATDYN=matdyn.x",
                       'LAMBDA="lambda.x"', "PYTHON='python3'"]
        self.assertEqual(names(script(assignments)), EXPECTED)

    def test_literal_referenced_paths_and_quote_aware_inline_comments(self):
        assignments = ['PW="/opt/qe/bin/pw.x"', 'PH=ph.x', 'Q2R=q2r.x', 'MATDYN=matdyn.x',
                       'LAMBDA=lambda.x', 'PYTHON=python3']
        commands = [x.replace('< scf.in', '< "decks#1/scf.in" # real comment')
                    if 'scf.in' in x and '--structure' not in x else x for x in STAGES]
        self.assertEqual(names(script(assignments, commands)), EXPECTED)

    def test_simple_argv_preserving_wrapper_single_and_multiline(self):
        assignments = ['PW="${PW:-pw.x}"', 'PH="${PH:-ph.x}"', 'Q2R="${Q2R:-q2r.x}"',
                       'MATDYN="${MATDYN:-matdyn.x}"', 'LAMBDA="${LAMBDA:-lambda.x}"',
                       'PYTHON="${PYTHON:-python3}"']
        one = 'run () { "$@" || exit 1; }\n' + script(assignments, ["run " + x for x in STAGES])
        multi = 'run() {\n  "$@" || exit 1\n}\n' + script(assignments, ["run " + x for x in STAGES])
        self.assertEqual(names(one), EXPECTED)
        self.assertEqual(names(multi), EXPECTED)

    def test_simple_unquoted_wrapper_argument_remains_supported(self):
        text = 'PW=${PW:-pw.x}\nrun() { "$@"; }\nrun $PW < scf.in # accepted legacy simple form\n'
        self.assertEqual(names(text), ["dense"])

    def test_backslash_continued_real_helper_command_is_recognized(self):
        slash = chr(92)
        helper = ("python3 make-lambda-input.py " + slash + "\n  --structure scf.in " + slash +
                  "\n  --elph-dir elph_dir --nq1 4 --nq2 4 --nq3 1 " + slash +
                  "\n  --emax 30 --degauss 0.12 --ngauss 0 --mu 0.16 0.10 # actual invocation")
        self.assertEqual(names(helper), ["qmap"])

    def test_reversed_and_missing_commands_do_not_form_required_order(self):
        assignments = ["PW=pw.x", "PH=ph.x", "Q2R=q2r.x", "MATDYN=matdyn.x", "LAMBDA=lambda.x"]
        reversed_names = names(script(assignments, list(reversed(STAGES))))
        missing_names = names(script(assignments, STAGES[:1] + STAGES[2:]))
        self.assertNotEqual(reversed_names, EXPECTED)
        self.assertNotEqual(missing_names, EXPECTED)
        self.assertNotEqual(reversed_names, [x for x in EXPECTED if x in reversed_names])

    def test_unknown_engine_and_dynamic_substitutions_are_unrecognized(self):
        text = ('PW="${PW:-pwfoo.x}"\n"$PW" < scf.in\n'
                'PW="$(command -v pw.x)"\n"$PW" < scf.in\n'
                '"$(command -v pw.x)" < scf.in\n')
        self.assertEqual(names(text), [])

    def test_single_quoted_self_default_is_literal_not_expansion(self):
        self.assertEqual(names("PW='${PW:-pw.x}'\n$PW < scf.in\n"), [])

    def test_echo_comments_and_quoted_text_cannot_fabricate_qe_or_qmap(self):
        text = '''# pw.x < scf.in
echo "pw.x < scf.in"
printf '%s' "python3 make-lambda-input.py --structure scf.in"
"pw.x < scf.in"
echo python3 make-lambda-input.py --structure scf.in --elph-dir elph_dir --nq1 4 --nq2 4 --nq3 1 --emax 30 --degauss 0.12 --ngauss 0 --mu 0.16 0.10
'''
        self.assertEqual(names(text), [])

    def test_qmap_requires_real_python_script_operand_but_allows_helper_args(self):
        canonical = "python3 make-lambda-input.py --scf scf.in --elph-root elph_dir --mesh 4 4 1"
        expanded = QMAP
        default_args = "python3 ./make-lambda-input.py"
        standard_flags = ["python3 -u make-lambda-input.py", "python3 -B -I -OO make-lambda-input.py",
                          "python3 -E -s -S -O make-lambda-input.py", "python3 -- make-lambda-input.py"]
        self.assertEqual(names(canonical), ["qmap"])
        self.assertEqual(names(expanded), ["qmap"])
        self.assertEqual(names(default_args), ["qmap"])
        for command in standard_flags:
            with self.subTest(command=command):
                self.assertEqual(names(command), ["qmap"])
        bad = ["echo " + QMAP, "not-python make-lambda-input.py --anything yes",
               "python3 fake-make-lambda-input.py --anything yes",
               "python3 -c 'make-lambda-input.py'", "python3 -m make-lambda-input.py",
               "python3 -h make-lambda-input.py", "python3 -V make-lambda-input.py",
               "python3 -W ignore make-lambda-input.py", "python3 make-lambda-input.py --help", "python3 make-lambda-input.py --version",
               "python3 make-lambda-input.py --path $UNKNOWN"]
        for command in bad:
            with self.subTest(command=command):
                self.assertEqual(names(command), [])


    def test_run_wrapper_requires_raw_double_quoted_at(self):
        for body in ["$@", "'$@'", 'echo "$@"', '"$@" | cat', '"$@"; echo done']:
            text = f'run() {{ {body}; }}\nrun "$PW" < scf.in\n'
            with self.subTest(body=body):
                self.assertEqual(names(text), [])

    def test_non_argv_preserving_wrapper_cannot_authorize_run_lines(self):
        text = 'run() { echo "$@"; }\nrun "$PW" < scf.in\n'
        self.assertEqual(names(text), [])


if __name__ == "__main__":
    unittest.main()
