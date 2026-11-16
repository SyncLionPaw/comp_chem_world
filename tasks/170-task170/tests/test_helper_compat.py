"""Focused basename-neutral helper structure regression; never executes helpers."""
from __future__ import annotations
import ast, json, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
CASE=HERE.parent
VERIFY=HERE/"verify.py"
REFERENCE=CASE/"solution"/"solve.py"
ASSETS=CASE/"environment"

class HelperCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=Path(tempfile.mkdtemp(prefix="case04-helper-compat-"))
        cls.base=cls.tmp/"reference-final"
        p=subprocess.run([sys.executable,str(REFERENCE),str(cls.base)],capture_output=True,text=True,timeout=20)
        if p.returncode: raise RuntimeError("trusted reference fixture generation failed")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp,ignore_errors=True)

    def clone(self,name):
        out=self.tmp/name
        shutil.copytree(self.base,out,dirs_exist_ok=True)
        return out

    def grade(self,final):
        env=os.environ.copy();env["APP"]=str(ASSETS)
        p=subprocess.run([sys.executable,str(VERIFY),str(final)],capture_output=True,text=True,env=env,timeout=20)
        self.assertIn(p.returncode,(0,1),p.stderr)
        return json.loads(p.stdout)

    def test_basename_neutral_deck_write_and_negative_controls(self):
        baseline=self.grade(self.base)
        self.assertEqual(baseline["overall"],"PASS",baseline.get("failed"))

        renamed=self.clone("renamed-helper-deck")
        helper=renamed/"make-lambda-input.py"
        helper.write_text(helper.read_text().replace('"lambda.in"','"qweight_deck.in"'))
        run=renamed/"run.sh"
        run.write_text(run.read_text().replace("lambda.in","qweight_deck.in"))
        result=self.grade(renamed)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))
        self.assertEqual({x["criterion"]:x["passed"] for x in baseline["checks"]},
                         {x["criterion"]:x["passed"] for x in result["checks"]})

        negatives=(
            ("missing-deck-write",lambda text:text.replace(".write_text(",".read_text(")),
            ("missing-second-mu",lambda text:text.replace('(.10,"lambda-mu010.in")','(.11,"lambda-mu010.in")')),
            ("missing-closed-coverage",lambda text:text.replace("sum(w for _,w,_ in rows)","16")),
        )
        for name,mutate in negatives:
            with self.subTest(name=name):
                out=self.clone(name)
                p=out/"make-lambda-input.py";original=p.read_text();changed=mutate(original)
                self.assertNotEqual(changed,original)
                p.write_text(changed)
                result=self.grade(out)
                self.assertEqual(result["overall"],"FAIL",result.get("failed"))
                failed={x["criterion"] for x in result["checks"] if not x["passed"]}
                self.assertEqual(failed,{"lambda_mapping_helper"})

    def test_private_header_reader_and_q_variables_are_alpha_renamable(self):
        out=self.clone("renamed-header-flow")
        helper=out/"make-lambda-input.py"
        text=helper.read_text()
        for old,new in (("read_ph_file","parse_q_header"),("q_tpiba","header_vector_49"),
                        ("q_cart","cartesian_q"),("q_frac","fractional_q"),
                        ("full_frac","mesh_points"),("grid_matches","matching_points")):
            text=re.sub(r"\b"+re.escape(old)+r"\b",new,text)
        helper.write_text(text)
        result=self.grade(out)
        baseline=self.grade(self.base)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))
        self.assertEqual({x["criterion"]:x["passed"] for x in baseline["checks"]},
                         {x["criterion"]:x["passed"] for x in result["checks"]})

        solved=self.clone("solve-reciprocal-flow")
        helper=solved/"make-lambda-input.py"
        code=helper.read_text()
        old="q_frac=np.mod(q_cart@np.linalg.inv(reciprocal),1.0)"
        self.assertIn(old,code)
        helper.write_text(code.replace(old,"q_frac=np.mod(np.linalg.solve(reciprocal.T,q_cart),1.0)"))
        result=self.grade(solved)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))

    def test_dataset_orbit_grid_flow_ignores_local_method_names(self):
        out=self.clone("dataset-flow")
        helper=out/"make-lambda-input.py"
        text=helper.read_text()
        fixture=("def classify_equivalence(symmetry_data):\n"
                 "    classes=[]\n"
                 "    for operation in symmetry_data[\"rotations\"]:\n"
                 "        classes.append(operation)\n"
                 "    return classes\n\n"
                 "def grid_locator(points, orbit_table):\n"
                 "    resolved={}\n"
                 "    for point in points:\n"
                 "        resolved[point]=orbit_table[0]\n"
                 "    return resolved\n\n")
        text=text.replace("def main():\n",fixture+"def main():\n")
        old='mapping,addresses=spglib.get_ir_reciprocal_mesh(mesh,(cell,positions,numbers),is_shift=(0,0,0),is_time_reversal=True,symprec=1e-5)'
        self.assertIn(old,text)
        text=text.replace(old,'dataset=spglib.get_symmetry_dataset((cell,positions,numbers))\n    mapping=classify_equivalence(dataset)\n    addresses=np.zeros((16,3))')
        text=text.replace('full_frac=np.mod(addresses/np.array(mesh),1.0)',
                          'full_frac=np.mod(addresses/np.array(mesh),1.0)\n    mapping=grid_locator(full_frac,mapping)')
        helper.write_text(text)
        result=self.grade(out)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))

        broken=self.clone("dataset-flow-disconnected")
        p=broken/"make-lambda-input.py"
        broken_text=helper.read_text().replace('mapping=grid_locator(full_frac,mapping)',
                                               'mapping=grid_locator(full_frac,{})')
        self.assertNotEqual(broken_text,helper.read_text())
        p.write_text(broken_text)
        result=self.grade(broken)
        self.assertEqual(result["overall"],"FAIL",result.get("failed"))
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertEqual(failed,{"lambda_mapping_helper"})

        indexed=self.clone("dataset-index-return")
        p=indexed/"make-lambda-input.py"
        indexed_text=helper.read_text().replace("resolved[point]=orbit_table[0]",
                                                 "resolved[point]=orbit_table[point]")
        indexed_text=indexed_text.replace("return resolved\n\ndef main():",
                                          "return resolved[points[0]]\n\ndef main():")
        indexed_text=indexed_text.replace("mapping=grid_locator(full_frac,mapping)",
                                          "grid_index=grid_locator(full_frac,mapping)\n    mapping=mapping[grid_index]")
        self.assertNotEqual(indexed_text,helper.read_text())
        p.write_text(indexed_text)
        result=self.grade(indexed)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))

        disconnected=self.clone("dataset-disconnected-index")
        p=disconnected/"make-lambda-input.py"
        broken=indexed_text.replace("grid_index=grid_locator(full_frac,mapping)",
                                    "grid_index=grid_locator(full_frac,{})")
        self.assertNotEqual(broken,indexed_text)
        p.write_text(broken)
        result=self.grade(disconnected)
        self.assertEqual(result["overall"],"FAIL",result.get("failed"))
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertEqual(failed,{"lambda_mapping_helper"})

    def test_renamed_sys_exit_wrapper_is_connected_to_rejection_guards(self):
        source=(CASE/"solution"/"make-lambda-input.py").read_text()
        class ReplaceRaises(ast.NodeTransformer):
            def visit_Raise(self,node):
                args=node.exc.args if isinstance(node.exc,ast.Call) else [ast.Constant(value="invalid")]
                return ast.copy_location(ast.Expr(ast.Call(func=ast.Name(id="fail",ctx=ast.Load()),args=args,keywords=[])),node)
        class RenameFail(ast.NodeTransformer):
            def visit_FunctionDef(self,node):
                if node.name=="fail": node.name="abort_internal"
                return self.generic_visit(node)
            def visit_Name(self,node):
                if node.id=="fail": node.id="abort_internal"
                return node
        class RemoveAbortCalls(ast.NodeTransformer):
            def visit_Expr(self,node):
                if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=="abort_internal":
                    return ast.copy_location(ast.Pass(),node)
                return self.generic_visit(node)
        tree=ReplaceRaises().visit(ast.parse(source))
        tree.body.insert(1,ast.Import(names=[ast.alias(name="sys")]))
        wrapper=ast.FunctionDef(name="fail",args=ast.arguments(posonlyargs=[],args=[ast.arg(arg="message")],kwonlyargs=[],kw_defaults=[],defaults=[ast.Constant(value=None)]),
                                body=[ast.Expr(ast.Call(func=ast.Attribute(value=ast.Name(id="sys",ctx=ast.Load()),attr="exit",ctx=ast.Load()),
                                                        args=[ast.Name(id="message",ctx=ast.Load())],keywords=[]))],decorator_list=[])
        tree.body.append(wrapper);ast.fix_missing_locations(tree)

        def grade_variant(name,variant):
            out=self.clone(name); helper=out/"make-lambda-input.py"
            variant=ast.parse(ast.unparse(variant));ast.fix_missing_locations(variant)
            helper.write_text(ast.unparse(variant)+"\n")
            return self.grade(out)

        renamed_tree=RenameFail().visit(ast.parse(ast.unparse(tree)))
        baseline=grade_variant("sys-exit-fail-baseline",tree)
        renamed=grade_variant("sys-exit-alpha-renamed",renamed_tree)
        self.assertEqual(baseline["overall"],"PASS",baseline.get("failed"))
        self.assertEqual(renamed["overall"],"PASS",renamed.get("failed"))
        no_guard_tree=RemoveAbortCalls().visit(ast.parse(ast.unparse(renamed_tree)))
        no_guard=grade_variant("sys-exit-noop-guards",no_guard_tree)
        self.assertEqual(no_guard["overall"],"FAIL",no_guard.get("failed"))
        failed={x["criterion"] for x in no_guard["checks"] if not x["passed"]}
        self.assertEqual(failed,{"lambda_mapping_helper"})

    def test_open_stream_writers_and_nonwriters(self):
        original=(CASE/"solution"/"make-lambda-input.py").read_text()
        old='        lines.append(f"{mu:.2f}"); (out/name).write_text("\\n".join(lines)+"\\n")'
        self.assertIn(old,original)
        for mode in ("w","w+","a","a+","x","x+"):
            with self.subTest(mode=mode):
                out=self.clone("open-writer-"+mode.replace("+","plus"))
                p=out/"make-lambda-input.py"
                new=(f'        lines.append(f"{{mu:.2f}}")\n'
                     f'        with open(out/name, "{mode}") as arbitrary_local_stream:\n'
                     '            arbitrary_local_stream.write("\\n".join(lines)+"\\n")')
                p.write_text(original.replace(old,new))
                result=self.grade(out)
                self.assertEqual(result["overall"],"PASS",result.get("failed"))

        negatives=(
            ("open-read-mode",'with open(out/name, "r") as handle:\n            handle.write("deck")'),
            ("open-without-write",'with open(out/name, "w") as stream:\n            stream.read()'),
        )
        for name,writer in negatives:
            with self.subTest(name=name):
                out=self.clone(name);p=out/"make-lambda-input.py"
                replacement='        lines.append(f"{mu:.2f}")\n        '+writer
                p.write_text(original.replace(old,replacement))
                result=self.grade(out)
                self.assertEqual(result["overall"],"FAIL",result.get("failed"))
                failed={x["criterion"] for x in result["checks"] if not x["passed"]}
                self.assertEqual(failed,{"lambda_mapping_helper"})

if __name__=="__main__": unittest.main()
