#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: No separate execution attestation is implied by checks of submitted results.
# L3 Science: Plan a QE 7.2 electron–phonon input chain.
"""Static scientific audit for the explicitly versioned QE 7.2 native EPC chain.

This checks syntax-level structure, parameters, dataflow and estimates. It does
not execute QE or establish that the estimated core-hours are achievable.
"""
from __future__ import annotations
import ast, hashlib, json, math, os, re, shlex, sys
from pathlib import Path

ANG_PER_BOHR = 0.529177210903
REQUIRED = ("plan.json", "scf.in", "coarse_scf.in", "ph.in", "q2r.in", "matdyn.in", "make-lambda-input.py", "run.sh")

def emit(status, message=None, checks=None):
    obj={"overall":status}
    if status in {"PASS","FAIL"}: obj["reward"]=1.0 if status=="PASS" else 0.0
    if message: obj["infra_error" if status=="ENV_INVALID" else "detail"]=message
    if checks is not None:
        obj["checks"]=checks; obj["failed"]=[c["criterion"] for c in checks if not c["passed"]]
    print(json.dumps(obj,ensure_ascii=False,indent=2))
    return {"PASS":0,"FAIL":1,"ENV_INVALID":2}[status]

def _validate_criteria(cfg):
    def number(value, *, positive=False):
        return type(value) in (int, float) and math.isfinite(float(value)) and (not positive or value > 0)
    def grid(value):
        return isinstance(value, list) and len(value) == 3 and all(type(x) is int and x > 0 for x in value)
    def pair(value):
        return isinstance(value, list) and len(value) == 2 and all(number(x, positive=True) for x in value) and value[0] <= value[1]
    if not isinstance(cfg, dict): raise ValueError("criteria must be an object")
    if not isinstance(cfg["qe_target"], str) or not re.fullmatch(r"\d+\.\d+", cfg["qe_target"]):
        raise ValueError("criteria.qe_target must be a version string")
    if not number(cfg["qe_structure_match_tolerance_A"], positive=True) or not number(cfg["ecutwfc_min_Ry"], positive=True):
        raise ValueError("criteria structure tolerance and cutoff must be finite and positive")
    if not pair(cfg["degauss_Ry"]) or not grid(cfg["dense_k"]) or not grid(cfg["q_grid"]):
        raise ValueError("criteria smearing bounds and fixed grids are invalid")
    if type(cfg["coarse_k_min_in_plane"]) is not int or cfg["coarse_k_min_in_plane"] < 1:
        raise ValueError("criteria.coarse_k_min_in_plane must be a positive integer")
    if not pair(cfg["cell_a_A"]) or not number(cfg["cell_c_min_A"], positive=True):
        raise ValueError("criteria cell bounds are invalid")
    if not number(cfg["budget_total_core_hours_max"], positive=True) or not number(cfg["budget_ph_core_hours_max"], positive=True) or cfg["budget_ph_core_hours_max"] > cfg["budget_total_core_hours_max"]:
        raise ValueError("criteria core-hour limits are invalid")
    if not number(cfg["budget_sum_abs_tolerance"], positive=True):
        raise ValueError("criteria.budget_sum_abs_tolerance must be finite and positive")
    mu = cfg["mu_star"]
    if not isinstance(mu, list) or len(mu) != 2 or not all(number(x, positive=True) and x < 1 for x in mu):
        raise ValueError("criteria.mu_star must contain two finite values between 0 and 1")

def parse_namelist(text):
    groups={}
    for m in re.finditer(r"(?ims)^\s*&([A-Za-z_]\w*)\s*(.*?)^\s*/\s*(?:!.*)?$", text):
        group=m.group(1).lower(); body=re.sub(r"!.*$","",m.group(2),flags=re.M)
        vals={}
        # Each match ends at the next assignment, so comma-separated and
        # multi-line Fortran namelist assignments are both handled.
        pat=r"([A-Za-z_]\w*(?:\(\d+\))?)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|([^,\s]+))"
        for a in re.finditer(pat,body):
            key=a.group(1).lower(); raw=next(x for x in a.groups()[1:] if x is not None).strip()
            low=raw.lower()
            if low in {".true.","true"}: v=True
            elif low in {".false.","false"}: v=False
            else:
                try: v=float(raw.replace("d","e").replace("D","e"))
                except ValueError: v=raw
                if isinstance(v,float) and v.is_integer(): v=int(v)
            vals[key]=v
        groups[group]=vals
    return groups

def card_grid(text):
    m=re.search(r"(?im)^\s*K_POINTS\s+automatic\s*\n\s*(\d+)\s+(\d+)\s+(\d+)\s+([+-]?\d+)\s+([+-]?\d+)\s+([+-]?\d+)",text)
    return list(map(int,m.groups())) if m else None

def parse_cell(text):
    m=re.search(r"(?im)^\s*CELL_PARAMETERS\s*(?:\(([^)]*)\)|\{([^}]*)\}|(\w+))\s*\n((?:\s*[-+0-9.eEdD]+\s+[-+0-9.eEdD]+\s+[-+0-9.eEdD]+\s*\n){3})",text)
    if not m:return None
    unit=next(x for x in m.groups()[:3] if x is not None).strip().lower()
    if unit in {"angstrom","ang"}: scale=1.0
    elif unit=="bohr": scale=ANG_PER_BOHR
    else:return None  # alat requires celldm(1); never assume alat means bohr.
    return [[float(x.replace('d','e').replace('D','e'))*scale for x in row.split()[:3]] for row in m.group(4).strip().splitlines()]

def parse_positions(text):
    m=re.search(r"(?im)^\s*ATOMIC_POSITIONS\s*\(([^)]*)\)\s*\n((?:\s*[A-Za-z]+\s+[-+0-9.eEdD]+\s+[-+0-9.eEdD]+\s+[-+0-9.eEdD]+[^\n]*\n)+)",text)
    if not m:return None
    return {"unit":m.group(1).strip().lower(),
            "atoms":[(p[0],tuple(float(x.replace('d','e').replace('D','e')) for x in p[1:4]))
                     for p in (ln.split() for ln in m.group(2).splitlines())]}

def parse_reference_poscar(path):
    lines=path.read_text().splitlines()
    if len(lines)<8: raise ValueError("reference POSCAR is truncated")
    scale=float(lines[1].strip())
    if not math.isfinite(scale) or scale<=0: raise ValueError("reference POSCAR scale must be positive")
    cell=[[float(x)*scale for x in lines[i].split()[:3]] for i in range(2,5)]
    species=lines[5].split(); counts=[int(x) for x in lines[6].split()]
    if len(species)!=len(counts) or sum(counts)!=5 or lines[7].strip().lower()!="direct":
        raise ValueError("reference POSCAR must be a five-atom Direct structure")
    atoms=[]; cursor=8
    for symbol,count in zip(species,counts):
        for _ in range(count):
            atoms.append((symbol,tuple(float(x) for x in lines[cursor].split()[:3])))
            cursor+=1
    return cell,atoms

def structure_matches_reference(cell, positions, reference_cell, reference_atoms, tol=1e-3):
    if positions is None or positions["unit"]!="crystal" or len(positions["atoms"])!=5:
        return False,"ATOMIC_POSITIONS must be crystal with exactly five atoms"
    cell_ok=all(abs(cell[i][j]-reference_cell[i][j])<=tol for i in range(3) for j in range(3))
    if not cell_ok: return False,"CELL_PARAMETERS differs from the declared reference POSCAR by >1e-3 A"
    submitted=positions["atoms"]
    if sorted(s for s,_ in submitted)!=sorted(s for s,_ in reference_atoms):
        return False,"submitted atomic species/counts do not match reference W2N3"

    def match_species(symbol, remaining_refs, candidate_indices):
        if not candidate_indices: return True
        i=candidate_indices[0]; s,frac=submitted[i]
        if s!=symbol: return False
        for j in remaining_refs:
            _,ref_frac=reference_atoms[j]
            delta=[frac[k]-ref_frac[k] for k in range(3)]
            delta=[d-round(d) for d in delta]
            cart=[sum(delta[k]*cell[k][axis] for k in range(3)) for axis in range(3)]
            if math.sqrt(sum(x*x for x in cart))<=tol and match_species(
                    symbol,[x for x in remaining_refs if x!=j],candidate_indices[1:]):
                return True
        return False

    for symbol in {s for s,_ in submitted}:
        refs=[i for i,(s,_) in enumerate(reference_atoms) if s==symbol]
        candidates=[i for i,(s,_) in enumerate(submitted) if s==symbol]
        if not match_species(symbol,refs,candidates):
            return False,f"submitted {symbol} fractional coordinates are not periodically equivalent to reference POSCAR"
    return True,"both SCF structures match the hash-checked W2N3 POSCAR within 1e-3 A periodic displacement"

def close(a,b,tol=1e-7):
    return isinstance(a,(int,float)) and not isinstance(a,bool) and math.isfinite(a) and abs(a-b)<=tol

def _grid3(value):
    return isinstance(value,list) and len(value)==3 and all(isinstance(x,int) and not isinstance(x,bool) and x>0 for x in value)

def _norm_path(value):
    if not isinstance(value,str) or not value.strip(): return None
    return re.sub(r"/+", "/", value.strip().replace("\\", "/")).rstrip("/") or "."

def _plan_views(plan):
    """Normalize the two typed public plan layouts documented in the contract."""
    route=plan.get("route")
    if isinstance(route,str):
        qe=plan.get("qe_target")
        order=plan.get("execution_order")
        grids=plan.get("grids")
        cost=plan.get("estimated_core_hours")
        basis=plan.get("estimate_basis")
        rationale=plan.get("justifications")
        uncertainty=plan.get("uncertainty", rationale)
        native="qe_native" in route.lower()
    elif isinstance(route,dict):
        qe=plan.get("qe_target_version")
        order=route.get("stages_in_order")
        km=plan.get("k_mesh"); qm=plan.get("q_mesh")
        grids={"dense_scf_k":km.get("dense",{}).get("grid") if isinstance(km,dict) else None,
               "coarse_scf_k":km.get("coarse",{}).get("grid") if isinstance(km,dict) else None,
               "q":qm.get("grid") if isinstance(qm,dict) else None}
        cost=plan.get("cost_estimate_core_hours")
        basis=cost.get("basis") if isinstance(cost,dict) else None
        rationale=plan.get("precision_vs_paper")
        uncertainty=plan.get("uncertainty", rationale)
        native="native" in str(route.get("name","")).lower()
    else:
        qe=order=grids=cost=basis=rationale=uncertainty=None; native=False
    return {"native":native,"qe":qe,"order":order,"grids":grids,"cost":cost,
            "basis":basis,"rationale":rationale,"uncertainty":uncertainty}

def _ordered_stages(order):
    aliases={"dense_scf_fit":"dense","coarse_scf":"coarse","ph":"ph","ph_dfpt":"ph",
             "q2r":"q2r","matdyn":"matdyn","matdyn_a2f":"matdyn","qmap_helper":"qmap",
             "lambda_postprocess":"qmap","lambda_mu016":"mu016","lambda_mu010":"mu010"}
    if not isinstance(order,list) or not order or not all(isinstance(x,str) for x in order): return None
    normalized=[aliases.get(x.strip().lower()) for x in order]
    if any(x is None for x in normalized): return None
    return normalized

def _strip_shell_comment(line):
    """Remove a shell comment without treating quoted # characters as comments."""
    out=[]; quote=None; escaped=False
    for ch in line:
        if escaped:
            out.append(ch); escaped=False; continue
        if ch=="\\" and quote!="'":
            out.append(ch); escaped=True; continue
        if quote is not None:
            out.append(ch)
            if ch==quote: quote=None
            continue
        if ch in ("'", '"'):
            quote=ch; out.append(ch); continue
        if ch=="#": break
        out.append(ch)
    return "".join(out)

def _shell_statements(text):
    """Join simple backslash continuations while retaining each statement's first line."""
    statements=[]; pending=""; first=1
    for number,raw in enumerate(text.splitlines(),1):
        line=raw.rstrip()
        if not pending: first=number
        slashes=len(line)-len(line.rstrip("\\"))
        if slashes%2:
            pending+=line[:-1]+" "
            continue
        statements.append((first,pending+line)); pending=""
    if pending: statements.append((first,pending))
    return statements

def _shell_words(text):
    """Tokenize one non-executed shell statement, keeping operators explicit."""
    lexer=shlex.shlex(text,posix=True,punctuation_chars="<>|&;()")
    lexer.whitespace_split=True
    lexer.commenters=""
    try: return list(lexer)
    except ValueError: return None

def _simple_shell_literal(value):
    return bool(value) and re.fullmatch(r"[A-Za-z0-9_./:+@%=-]+",value) is not None

def _assignment_value(line, variables):
    """Record only literal assignments and exact self-defaults; never evaluate shell."""
    m=re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)",line.strip())
    if not m: return False
    name,rhs=m.groups(); value=None
    if len(rhs)>=2 and rhs[0]==rhs[-1]=='"':
        inner=rhs[1:-1]
        default=re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^{}$`]+)\}",inner)
        if default and default.group(1)==name and _simple_shell_literal(default.group(2)):
            value=default.group(2)
        elif "$" not in inner and "`" not in inner and _simple_shell_literal(inner):
            value=inner
    elif len(rhs)>=2 and rhs[0]==rhs[-1]=="'":
        # Single quotes suppress parameter expansion in shell. Keep the contents
        # literal so '${PW:-pw.x}' cannot masquerade as a usable executable.
        inner=rhs[1:-1]
        if _simple_shell_literal(inner) or "$" in inner or "`" in inner:
            value=inner
    else:
        default=re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^{}$`]+)\}",rhs)
        if default and default.group(1)==name and _simple_shell_literal(default.group(2)):
            value=default.group(2)
        elif _simple_shell_literal(rhs):
            value=rhs
    if value is None:
        variables.pop(name,None)
    else:
        variables[name]=value
    return True

def _resolve_shell_word(word, variables):
    m=re.fullmatch(r"\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}",word)
    if m: return variables.get(m.group(1) or m.group(2))
    if "$" in word or "`" in word: return None
    return word

def _is_qmap_command(tokens, variables):
    """Require a real Python script invocation, not text or an interpreter mode."""
    if len(tokens)<2: return False
    exe=_resolve_shell_word(tokens[0],variables)
    if exe is None: return False
    executable=Path(exe).name.lower()
    if not re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)*)?",executable): return False
    # Python no-operand flags may precede a script. Do not treat -c/-m, options
    # that consume operands, or other execution modes as the helper invocation.
    no_operand_flags={"-u","-B","-I","-E","-s","-S","-O","-OO"}
    index=1
    while index<len(tokens) and tokens[index] in no_operand_flags:
        index+=1
    if index<len(tokens) and tokens[index]=="--": index+=1
    if index>=len(tokens): return False
    script=_resolve_shell_word(tokens[index],variables)
    if script is None or Path(script).name!="make-lambda-input.py": return False
    args=[]
    for token in tokens[index+1:]:
        value=_resolve_shell_word(token,variables)
        if value is None: return False
        args.append(value)
    # These modes do not invoke the helper's work path.
    if any(x in {"-h","--help","--version","-V"} for x in args): return False
    return True

def _resolve_run_stages(run):
    """Statically recognize verified QE inputs and the known Python q-map helper.

    Candidate scripts are tokenized but never sourced, evaluated, or executed.
    Unknown expansion, shell control composition, and non-argv-preserving run
    wrappers are ignored rather than guessed.
    """
    variables={}; statements=_shell_statements(run); wrapper_seen=False; wrapper_ok=True
    executable_lines=[]; i=0
    while i<len(statements):
        lineno,raw=statements[i]; line=_strip_shell_comment(raw).strip(); i+=1
        if not line: continue
        declaration=re.match(r"^run\s*\(\s*\)\s*\{(.*)$",line)
        if declaration:
            wrapper_seen=True; body=[]; tail=declaration.group(1)
            close=tail.find("}")
            if close>=0:
                body.append(tail[:close]); trailing=tail[close+1:].strip().rstrip(";").strip()
                if trailing: wrapper_ok=False
            else:
                body.append(tail)
                closed=False
                while i<len(statements):
                    _,part=statements[i]; i+=1; clean=_strip_shell_comment(part).strip()
                    close=clean.find("}")
                    if close>=0:
                        body.append(clean[:close]); trailing=clean[close+1:].strip().rstrip(";").strip()
                        if trailing: wrapper_ok=False
                        closed=True; break
                    body.append(clean)
                if not closed: wrapper_ok=False
            body_text="\n".join(body).strip().rstrip(";").strip()
            if not re.fullmatch(r'"\$@"(?:\s*\|\|\s*exit\s+1)?',body_text): wrapper_ok=False
            continue
        if line in {"}","set -u","set -euo pipefail","set -o pipefail"} or line.startswith("set "): continue
        if _assignment_value(line,variables): continue
        tokens=_shell_words(line)
        if tokens: executable_lines.append((lineno,tokens))
    wrapper=wrapper_seen and wrapper_ok
    stages=[]; lambda_seen=0
    for lineno,tokens in executable_lines:
        if not tokens: continue
        if tokens[0]=="run":
            if not wrapper: continue
            tokens=tokens[1:]
        if not tokens: continue
        # The helper is accepted only as an actual python invocation with the
        # complete, known argument shape. A filename mention or echo is not enough.
        if not any(x in tokens for x in ("<",">","|","||","&&",";","(",")")) and _is_qmap_command(tokens,variables):
            stages.append(("qmap",lineno)); continue
        if tokens.count("<")!=1: continue
        redir=tokens.index("<")
        command=tokens[:redir]; tail=tokens[redir+1:]
        if not command or not tail or any(x in command for x in ("<",">","|","||","&&",";","(",")")): continue
        if len(tail)>=1 and tail[0] in (">","<","|","||","&&",";","(",")"): continue
        input_word=_resolve_shell_word(tail[0],variables)
        if input_word is None: continue
        rest=tail[1:]
        if rest:
            if len(rest)!=2 or rest[0]!=">" or not _resolve_shell_word(rest[1],variables): continue
        resolved=[_resolve_shell_word(x,variables) for x in command]
        if any(x is None for x in resolved): continue
        exe=Path(resolved[0]).name.lower(); input_name=Path(input_word).name.lower()
        if exe=="pw.x" and input_name=="scf.in": stage="dense"
        elif exe=="pw.x" and input_name=="coarse_scf.in": stage="coarse"
        elif exe=="ph.x" and input_name=="ph.in": stage="ph"
        elif exe=="q2r.x" and input_name=="q2r.in": stage="q2r"
        elif exe=="matdyn.x" and input_name=="matdyn.in": stage="matdyn"
        elif exe=="lambda.x":
            if "016" in input_name or ".16" in input_name: stage="mu016"
            elif "010" in input_name or ".10" in input_name: stage="mu010"
            else: stage="mu016" if lambda_seen==0 else "mu010"
            lambda_seen+=1
        else: continue
        stages.append((stage,lineno))
    return stages

def _has_paired_mu_deck_writer(tree):
    """Require a deck writer in a loop that uses its loop-bound value."""
    import ast
    for loop in (n for n in ast.walk(tree) if isinstance(n,(ast.For,ast.AsyncFor))):
        targets={n.id for n in ast.walk(loop.target) if isinstance(n,ast.Name)}
        body=[n for stmt in loop.body for n in ast.walk(stmt)]
        uses_target=bool(targets & {n.id for n in body if isinstance(n,ast.Name)})
        writes_deck=any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                        and n.func.attr=="write_text" for n in body)
        if not writes_deck:
            for scope in (n for n in body if isinstance(n,(ast.With,ast.AsyncWith))):
                for item in scope.items:
                    opener=item.context_expr
                    if not (isinstance(opener,ast.Call) and isinstance(opener.func,ast.Name)
                            and opener.func.id=="open" and len(opener.args)>=2):
                        continue
                    mode=opener.args[1]
                    if not (isinstance(mode,ast.Constant) and isinstance(mode.value,str)
                            and mode.value[:1] in {"w","a","x"}):
                        continue
                    handles={n.id for n in ast.walk(item.optional_vars) if isinstance(n,ast.Name)} if item.optional_vars else set()
                    writes_deck=any(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                                    and call.func.attr=="write" and isinstance(call.func.value,ast.Name)
                                    and call.func.value.id in handles
                                    for child in scope.body for call in ast.walk(child))
                    if writes_deck: break
                if writes_deck: break
        if targets and uses_target and writes_deck:
            return True
    return False

def _assignment_names(node):
    targets=node.targets if isinstance(node,ast.Assign) else [node.target] if isinstance(node,ast.AnnAssign) else []
    return {target.id for item in targets for target in ast.walk(item) if isinstance(target,ast.Name)}

def _call_name(call):
    if isinstance(call.func,ast.Name): return call.func.id
    if isinstance(call.func,ast.Attribute): return call.func.attr
    return None

def _scope_nodes(scope):
    stack=[scope]
    while stack:
        node=stack.pop(); yield node
        for child in reversed(list(ast.iter_child_nodes(node))):
            if child is not scope and isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda)):
                continue
            stack.append(child)

def _has_header_to_grid_flow(tree):
    """Recognize a parsed PH q header flowing through unit conversion to a full-grid comparison."""
    local_readers=set()
    for fn in (n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))):
        calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call)]
        attrs={n.func.attr for n in calls if isinstance(n.func,ast.Attribute)}
        names={n.func.id for n in calls if isinstance(n.func,ast.Name)}
        if {"read_text","splitlines"}.issubset(attrs) and "float" in names and "array" in attrs:
            local_readers.add(fn.name)
    for scope in (n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))):
        nodes=list(_scope_nodes(scope)); assignments=[n for n in nodes if isinstance(n,(ast.Assign,ast.AnnAssign))]
        header_vectors=set()
        for node in assignments:
            value=node.value
            if isinstance(value,ast.Call) and _call_name(value) in local_readers:
                header_vectors.update(_assignment_names(node))
        converted=set()
        for node in assignments:
            value=node.value; names={n.id for n in ast.walk(value) if isinstance(n,ast.Name)}
            attrs={n.attr for n in ast.walk(value) if isinstance(n,ast.Attribute)}
            if (names & header_vectors and "pi" in attrs
                    and any(isinstance(n,ast.Constant) and n.value==2 for n in ast.walk(value))
                    and any(isinstance(n,ast.Div) for n in ast.walk(value))):
                converted.update(_assignment_names(node))
        mapped=set(); grids=set()
        for node in assignments:
            value=node.value; names={n.id for n in ast.walk(value) if isinstance(n,ast.Name)}
            calls=[n for n in ast.walk(value) if isinstance(n,ast.Call)]
            attrs={n.func.attr for n in calls if isinstance(n.func,ast.Attribute)}
            has_inverse_map=("inv" in attrs and any(isinstance(n,ast.MatMult) for n in ast.walk(value))
                             or "solve" in attrs)
            if names & converted and has_inverse_map:
                mapped.update(_assignment_names(node))
            if "mod" in attrs and any(isinstance(n,ast.Div) for n in ast.walk(value)):
                grids.update(_assignment_names(node))
        if not mapped or not grids: continue
        for loop in (n for n in nodes if isinstance(n,(ast.For,ast.AsyncFor))):
            iter_names={n.id for n in ast.walk(loop.iter) if isinstance(n,ast.Name)}
            if not iter_names & grids: continue
            body=list(_scope_nodes(loop)); compared=set(mapped)
            for _ in range(len(body)):
                for statement in body:
                    if isinstance(statement,(ast.Assign,ast.AnnAssign)):
                        if {n.id for n in ast.walk(statement.value) if isinstance(n,ast.Name)} & compared:
                            compared.update(_assignment_names(statement))
                    elif isinstance(statement,ast.AugAssign) and isinstance(statement.target,ast.Name):
                        if statement.target.id in compared or {n.id for n in ast.walk(statement.value) if isinstance(n,ast.Name)} & compared:
                            compared.add(statement.target.id)
            if any(isinstance(n,ast.Compare) and any(isinstance(x,ast.Name) and x.id in compared for x in ast.walk(n)) for n in body):
                return True
    return False

def _has_dataset_orbit_flow(tree):
    """Recognize dataset→local orbit-table→grid-lookup connected AST definitions and uses."""
    functions={n.name:n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    for scope in (n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))):
        nodes=list(_scope_nodes(scope)); assignments=[n for n in nodes if isinstance(n,(ast.Assign,ast.AnnAssign))]
        datasets=set()
        for node in assignments:
            value=node.value
            if isinstance(value,ast.Call) and _call_name(value)=="get_symmetry_dataset":
                datasets.update(_assignment_names(node))
        if not datasets: continue
        calls=[n for n in nodes if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in functions]
        first_results=set(); first_functions=set()
        for call in calls:
            fn=functions[call.func.id]; params=[*fn.args.posonlyargs,*fn.args.args]
            for i,arg in enumerate(call.args):
                if i>=len(params) or not any(isinstance(n,ast.Name) and n.id in datasets for n in ast.walk(arg)): continue
                param=params[i].arg; body=list(ast.walk(fn))
                subscript_use=any(isinstance(n,ast.Subscript) and any(isinstance(x,ast.Name) and x.id==param for x in ast.walk(n.value)) for n in body)
                if not (subscript_use and any(isinstance(n,(ast.For,ast.AsyncFor,ast.comprehension)) for n in body)): continue
                first_functions.add(fn.name)
                for assign in assignments:
                    if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id==fn.name for n in ast.walk(assign.value)):
                        first_results.update(_assignment_names(assign))
        for call in calls:
            if call.func.id in first_functions: continue
            fn=functions[call.func.id]; params=[*fn.args.posonlyargs,*fn.args.args]
            for i,arg in enumerate(call.args):
                if i>=len(params) or not any(isinstance(n,ast.Name) and n.id in first_results for n in ast.walk(arg)): continue
                param=params[i].arg; body=list(ast.walk(fn))
                subscript_use=any(isinstance(n,ast.Subscript) and any(isinstance(x,ast.Name) and x.id==param for x in ast.walk(n.value)) for n in body)
                iterates=any(isinstance(n,(ast.For,ast.AsyncFor,ast.comprehension)) for n in body)
                if not (subscript_use and iterates): continue
                result_names=set()
                for assign in assignments:
                    if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id==fn.name for n in ast.walk(assign.value)):
                        result_names.update(_assignment_names(assign))
                for subscript in (n for n in nodes if isinstance(n,ast.Subscript)):
                    table_names={n.id for n in ast.walk(subscript.value) if isinstance(n,ast.Name)}
                    index_names={n.id for n in ast.walk(subscript.slice) if isinstance(n,ast.Name)}
                    if table_names & result_names or (table_names & first_results and index_names & result_names):
                        return True
    return False

def _has_connected_rejection(tree):
    if any(isinstance(n,ast.Raise) for n in ast.walk(tree)): return True
    imported_sys={a.asname or a.name for n in ast.walk(tree) if isinstance(n,ast.Import)
                  for a in n.names if a.name=="sys"}
    if not imported_sys: return False
    wrappers=set()
    for fn in (n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))):
        if any(isinstance(c,ast.Call) and isinstance(c.func,ast.Attribute)
               and c.func.attr=="exit" and isinstance(c.func.value,ast.Name)
               and c.func.value.id in imported_sys for c in ast.walk(fn)):
            wrappers.add(fn.name)
    if not wrappers: return False
    entry_names=set()
    for guard in (n for n in tree.body if isinstance(n,ast.If)):
        if any(isinstance(c,ast.Compare) and any(isinstance(x,ast.Name) and x.id=="__name__" for x in ast.walk(c))
               and any(isinstance(x,ast.Constant) and x.value=="__main__" for x in ast.walk(c)) for c in ast.walk(guard.test)):
            entry_names.update(c.func.id for c in ast.walk(guard) if isinstance(c,ast.Call) and isinstance(c.func,ast.Name))
    for fn in (n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in entry_names):
        for branch in (n for n in _scope_nodes(fn) if isinstance(n,ast.If)):
            test_calls={_call_name(n) for n in ast.walk(branch.test) if isinstance(n,ast.Call)}
            has_weight_guard="sum" in test_calls
            has_membership_guard=any(isinstance(n,ast.Compare) and any(isinstance(op,(ast.In,ast.NotIn)) for op in n.ops)
                                     for n in ast.walk(branch.test))
            if not (has_weight_guard or has_membership_guard): continue
            if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in wrappers
                   for stmt in branch.body for n in ast.walk(stmt)):
                return True
    return False

def _looks_unmeasured(text):
    s=str(text or "").lower()
    unresolved=("unresolved","not established","not measured","not assessed","not been assessed","not benchmarked","no benchmark","unbenchmarked","uncertain","unknown","需验证","尚未验证","尚未测量","尚未进行基准测时","未测","不确定","尚不清楚","未知")
    return any(x in s for x in unresolved)

def _has_unsupported_direction(text):
    s=str(text or "").lower()
    claims=("underestimates","is underestimated","will underestimate","expected to be underestimated",
            "definitely underestimates","一定低估","必然低估","预计低估","误差方向为")
    return any(_has_asserted_phrase(clause,claims) for clause in _claim_clauses(s))

def _claim_clauses(text):
    # Keep epistemic qualifiers local: a separate sentence/clause saying
    # "convergence unknown" must not neutralize an earlier definite claim.
    return [x.strip() for x in re.split(r"[.!?;。！？；]|\bbut\b|\bhowever\b|\bwhereas\b|\balthough\b|\bthough\b|但是|然而|不过",str(text or "").lower()) if x.strip()]

def _has_asserted_phrase(clause,phrases):
    for phrase in phrases:
        at=clause.find(phrase)
        if at<0: continue
        prefix=clause[max(0,at-90):at]
        # Local denial/epistemic language negates the assertion itself.
        if re.search(r"(?:cannot|can't|could not|not established|not proven|not demonstrated|not shown|no evidence(?: that)?|cannot conclude|cannot infer|not conclude|not infer|不应断言|不能断言|不能得出|无法得出|尚不能证明|没有证据表明)[^.!?;。！？；]*$",prefix):
            continue
        if any(x in prefix[-70:] for x in ("uncertain whether","unclear whether","unknown whether","not necessarily","whether or not","尚不清楚是否","不能确定是否")):
            continue
        return True
    return False

def _has_unverified_error_claim(text):
    s=str(text or "").lower()
    no_extra=("not additional error source","no additional error source","not an additional error",
              "no extra error","no added error","没有额外误差","不产生额外误差","不是额外误差来源")
    return _has_unsupported_direction(s) or any(_has_asserted_phrase(c,no_extra) for c in _claim_clauses(s))

def main(argv):
    final=Path(argv[1] if len(argv)>1 else "/app/final").resolve(); tests=Path(__file__).resolve().parent
    refs=tests/"refs.json"; assets=Path(os.environ.get("APP","/app"))/"assets"
    if not refs.is_file(): return emit("ENV_INVALID","tests/refs.json missing")
    try:
        ref=json.loads(refs.read_text())
        if not isinstance(ref,dict) or not isinstance(ref.get("asset_hashes"),dict): raise ValueError("asset_hashes must be an object")
        cfg=ref["criteria"]
        _validate_criteria(cfg)
    except Exception as e:return emit("ENV_INVALID",f"invalid refs.json: {e}")
    for key,expected in ref["asset_hashes"].items():
        path=assets/Path(key).name
        if not path.is_file():return emit("ENV_INVALID",f"public asset missing: {path.name}")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected.removeprefix("sha256:"):
            return emit("ENV_INVALID",f"public asset hash mismatch: {path.name}")
    reference_path=assets/"W2N3-monolayer.poscar"
    try:
        reference_cell,reference_atoms=parse_reference_poscar(reference_path)
    except Exception as e:return emit("ENV_INVALID",f"trusted reference POSCAR is invalid: {e}")
    missing=[n for n in REQUIRED if not (final/n).is_file()]
    if missing:return emit("FAIL",f"missing deliverables: {missing}",[{"criterion":"deliverables_present","level":"L1","passed":False,"detail":str(missing)}])
    try:
        plan=json.loads((final/"plan.json").read_text())
        texts={n:(final/n).read_text() for n in REQUIRED if n.endswith(".in")}
        run=(final/"run.sh").read_text(); helper=(final/"make-lambda-input.py").read_text()
    except Exception as e:return emit("FAIL",f"answer files unreadable or invalid JSON: {e}",[{"criterion":"answer_readable","level":"L1","passed":False,"detail":str(e)}])
    if not isinstance(plan,dict):return emit("FAIL","plan.json must be a JSON object",[{"criterion":"plan_schema","level":"L1","passed":False,"detail":"top-level value must be object"}])
    checks=[]
    def ck(name,ok,detail,level="L2"):
        checks.append({"criterion":name,"level":level,"passed":bool(ok),"detail":str(detail)})
    # QE 7.2 namelists and structures.
    nls={n:parse_namelist(t) for n,t in texts.items()}
    dense=nls["scf.in"].get("system",{}); coarse=nls["coarse_scf.in"].get("system",{})
    ctrl_dense=nls["scf.in"].get("control",{}); ctrl_coarse=nls["coarse_scf.in"].get("control",{})
    ph=nls["ph.in"].get("inputph",{}); q2r=nls["q2r.in"].get("input",{}); mat=nls["matdyn.in"].get("input",{})
    pv=_plan_views(plan)
    compact=isinstance(plan.get("route"),str)
    if compact:
        schema_ok=(plan.get("route")=="qe_native" and isinstance(plan.get("qe_target"),str)
                   and isinstance(plan.get("execution_order"),list) and isinstance(plan.get("structure"),dict)
                   and isinstance(plan.get("cutoffs"),dict) and isinstance(plan.get("smearing"),dict)
                   and isinstance(plan.get("grids"),dict) and isinstance(plan.get("estimated_core_hours"),dict)
                   and isinstance(plan.get("estimate_basis"),str) and isinstance(plan.get("justifications"),dict))
        sm=plan.get("smearing",{}); cut=plan.get("cutoffs",{}); st=plan.get("structure",{}); gr=plan.get("grids",{})
        schema_ok=(schema_ok and st.get("n_atoms")==5 and isinstance(st.get("cell_height_z_A"),(int,float))
                   and isinstance(cut.get("ecutwfc_ry"),(int,float)) and cut.get("ecutwfc_ry",0)>=cfg["ecutwfc_min_Ry"]
                   and sm.get("occupations")=="smearing" and isinstance(sm.get("degauss_ry"),(int,float))
                   and cfg["degauss_Ry"][0]<=sm.get("degauss_ry",0)<=cfg["degauss_Ry"][1]
                   and _grid3(gr.get("dense_scf_k")) and gr.get("dense_scf_k")==cfg["dense_k"] and _grid3(gr.get("coarse_scf_k"))
                   and gr["coarse_scf_k"][0]>=cfg["coarse_k_min_in_plane"] and gr["coarse_scf_k"][1]>=cfg["coarse_k_min_in_plane"] and gr["coarse_scf_k"][2]==1
                   and _grid3(gr.get("q")) and gr.get("q")==cfg["q_grid"])
    elif isinstance(plan.get("route"),dict):
        data=plan.get("data_flow");mapping=plan.get("q_file_mapping");st=plan["route"].get("stages_in_order")
        schema_ok=(isinstance(plan.get("case"),str) and isinstance(plan.get("material"),str)
                   and isinstance(plan.get("qe_target_version"),str) and isinstance(st,list)
                   and isinstance(plan.get("structure"),dict) and isinstance(plan.get("cutoffs"),dict)
                   and isinstance(plan.get("smearing"),dict) and isinstance(plan.get("k_mesh"),dict)
                   and isinstance(plan.get("q_mesh"),dict) and isinstance(data,list) and bool(data)
                   and all(isinstance(x,dict) and all(isinstance(x.get(k),str) for k in ("stage","program","input","reads","note")) and isinstance(x.get("writes"),list) for x in data)
                   and isinstance(mapping,dict) and all(isinstance(mapping.get(k),str) for k in ("method","units_in_ph_header","conversion","orbit_table","on_failure"))
                   and isinstance(mapping.get("fail_closed_conditions"),list)
                   and isinstance(plan.get("cost_estimate_core_hours"),dict)
                   and isinstance(plan.get("precision_vs_paper"),dict)
                   and isinstance(plan.get("assumptions_and_caveats"),list)
                   and isinstance(plan.get("deliverables"),list))
        sm=plan.get("smearing",{}); cut=plan.get("cutoffs",{}); st=plan.get("structure",{}); km=plan.get("k_mesh",{}); qm=plan.get("q_mesh",{})
        schema_ok=(schema_ok and st.get("nat")==5 and st.get("formula")=="W2N3"
                   and isinstance(cut.get("ecutwfc_ry"),(int,float)) and cut.get("ecutwfc_ry",0)>=cfg["ecutwfc_min_Ry"]
                   and sm.get("occupations")=="smearing" and isinstance(sm.get("degauss_ry"),(int,float)) and cfg["degauss_Ry"][0]<=sm.get("degauss_ry",0)<=cfg["degauss_Ry"][1]
                   and isinstance(km.get("dense"),dict) and _grid3(km["dense"].get("grid")) and km["dense"].get("grid")==cfg["dense_k"]
                   and isinstance(km.get("coarse"),dict) and _grid3(km["coarse"].get("grid"))
                   and km["coarse"]["grid"][0]>=cfg["coarse_k_min_in_plane"] and km["coarse"]["grid"][1]>=cfg["coarse_k_min_in_plane"] and km["coarse"]["grid"][2]==1
                   and _grid3(qm.get("grid")) and qm.get("grid")==cfg["q_grid"]
                   and all(isinstance(x,str) for x in plan.get("assumptions_and_caveats",[]))
                   and all(isinstance(x,str) for x in plan.get("deliverables",[])))
    else: schema_ok=False
    ck("plan_schema",schema_ok,"plan.json matches one complete typed public layout (compact or expanded), including route, structural/setup fields, grids, cost estimates, data flow/mapping when expanded, and rationale")
    qe=str(pv["qe"]).strip().lower().replace("quantum espresso ","") if pv["qe"] is not None else ""
    ck("qe_version_scope",qe in {f"qe {cfg['qe_target']}",cfg["qe_target"]},pv["qe"],"L1")
    ck("dense_la2f",dense.get("la2f") is True,"dense pw.x &SYSTEM sets la2F=.true.","L3")
    same_prefix=bool(ctrl_dense.get("prefix")) and str(ctrl_dense.get("prefix")).lower()==str(ctrl_coarse.get("prefix")).lower()
    same_outdir=bool(ctrl_dense.get("outdir")) and _norm_path(str(ctrl_dense.get("outdir")))==_norm_path(str(ctrl_coarse.get("outdir")))
    ph_prefix=(not ph.get("prefix") or str(ph.get("prefix")).lower()==str(ctrl_coarse.get("prefix")).lower())
    ph_outdir=(not ph.get("outdir") or _norm_path(str(ph.get("outdir")))==_norm_path(str(ctrl_coarse.get("outdir"))))
    dvscf=ph.get("fildvscf")
    ck("ph_interpolated",ph.get("electron_phonon")=="interpolated" and isinstance(dvscf,str) and bool(dvscf.strip()) and ph_prefix and ph_outdir,"ph.x uses interpolated electron_phonon, declares dvscf output, and shares SCF prefix/outdir", "L3")
    ph_dyn=ph.get("fildyn") or "prefix.dyn"
    q_dyn=q2r.get("fildyn")
    q_fc=q2r.get("flfrc")
    ck("q2r_la2f",q2r.get("la2f") is True and _norm_path(str(q_dyn))==_norm_path(str(ph_dyn)) and isinstance(q_fc,str) and bool(q_fc.strip()),"q2r la2F consumes the PH-declared dyn output and declares its force-constant output","L3")
    mat_fc=mat.get("flfrc")
    ck("matdyn_a2f_dos",mat.get("la2f") is True and mat.get("dos") is True and isinstance(mat.get("fldos"),str) and bool(mat["fldos"].strip()) and _norm_path(str(mat_fc))==_norm_path(str(q_fc)) and all(isinstance(mat.get(k),int) and mat[k]>0 for k in ("nk1","nk2","nk3")),"matdyn la2F/DOS consumes q2r-declared force constants and names a DOS output", "L3")
    # Input syntax/system settings.
    for name,nl in (("dense",nls["scf.in"]),("coarse",nls["coarse_scf.in"])):
        sysnl=nl.get("system",{}); ctl=nl.get("control",{})
        ck(f"{name}_pw_input",ctl.get("calculation")=="scf" and bool(ctl.get("prefix")) and bool(ctl.get("outdir")) and sysnl.get("nat")==5 and sysnl.get("ntyp")==2,"valid SCF with matching named prefix/outdir and 5-atom settings", "L2")
        ck(f"{name}_cutoff_smearing",isinstance(sysnl.get("ecutwfc"),(int,float)) and sysnl["ecutwfc"]>=cfg["ecutwfc_min_Ry"] and sysnl.get("occupations")=="smearing" and isinstance(sysnl.get("degauss"),(int,float)) and .005<=sysnl["degauss"]<=.02,f"ecutwfc={sysnl.get('ecutwfc')}, occupations={sysnl.get('occupations')}, degauss={sysnl.get('degauss')}","L3")
    gd=card_grid(texts["scf.in"]); gc=card_grid(texts["coarse_scf.in"])
    ck("dense_k_grid",gd is not None and gd[:3]==cfg["dense_k"] and gd[3:]==[0,0,0],f"dense unshifted mesh {gd}","L3")
    ck("coarse_k_grid",gc is not None and gc[0]>=cfg["coarse_k_min_in_plane"] and gc[1]>=cfg["coarse_k_min_in_plane"] and gc[2]==1,f"coarse mesh {gc}","L3")
    cells=[parse_cell(texts[n]) for n in ("scf.in","coarse_scf.in")]
    poses=[parse_positions(texts[n]) for n in ("scf.in","coarse_scf.in")]
    same_cell=all(cells) and all(close(cells[0][i][j],cells[1][i][j]) for i in range(3) for j in range(3))
    same_pos=poses[0] is not None and poses[0]==poses[1]
    ck("structure_consistency",same_cell and same_pos,f"same cell and positions block (including units)={same_cell and same_pos}")
    reference_checks=[]
    for name,cell,pos in zip(("scf.in","coarse_scf.in"),cells,poses):
        ok,detail=structure_matches_reference(cell,pos,reference_cell,reference_atoms,cfg["qe_structure_match_tolerance_A"]) if cell else (False,"CELL_PARAMETERS missing or invalid")
        reference_checks.append((name,ok,detail))
    ck("reference_structure_match",all(ok for _,ok,_ in reference_checks),"; ".join(f"{name}: {detail}" for name,_,detail in reference_checks),"L3")
    if cells[0]:
        a=math.hypot(cells[0][0][0],cells[0][0][1]); c=math.sqrt(sum(x*x for x in cells[0][2]))
    else:a=c=None
    ck("cell_2d_vacuum",a is not None and cfg["cell_a_A"][0]<=a<=cfg["cell_a_A"][1] and c is not None and c>=cfg["cell_c_min_A"],f"a={a}, c={c} Å")
    qmesh=[ph.get("nq1"),ph.get("nq2"),ph.get("nq3")]
    ck("ph_q_mesh",qmesh==cfg["q_grid"],f"unshifted ldisp q mesh={qmesh}","L3")
    try:
        import ast
        tree=ast.parse(helper)
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        call_names=[]
        for n in calls:
            if isinstance(n.func,ast.Name): call_names.append(n.func.id)
            elif isinstance(n.func,ast.Attribute): call_names.append(n.func.attr)
        string_constants={n.value.lower() for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
        imported_spglib=any(a.name=="spglib" for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names)
        numeric_constants={n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,(int,float)) and not isinstance(n.value,bool)}
        paired_mu=False
        for node in ast.walk(tree):
            if isinstance(node,(ast.Tuple,ast.List)):
                sub={n.value for n in ast.walk(node) if isinstance(n,ast.Constant) and isinstance(n.value,(int,float)) and not isinstance(n.value,bool)}
                if any(abs(float(x)-cfg["mu_star"][0])<1e-9 for x in sub) and any(abs(float(x)-cfg["mu_star"][1])<1e-9 for x in sub): paired_mu=True
        orbit_builder=("get_ir_reciprocal_mesh" in call_names or _has_dataset_orbit_flow(tree))
        closed_mapping=(_has_header_to_grid_flow(tree) and "sum" in call_names and "len" in call_names
                        and _has_connected_rejection(tree)
                        and any(isinstance(n,ast.Compare) and any(isinstance(op,(ast.In,ast.NotIn)) for op in n.ops) for n in ast.walk(tree)))
        helper_ok=(imported_spglib and orbit_builder and closed_mapping
                   and paired_mu and _has_paired_mu_deck_writer(tree)
                   and any("elph.inp_lambda.*" in x for x in string_constants)
                   )
    except (SyntaxError,ValueError): helper_ok=False
    ck("lambda_mapping_helper",helper_ok,"helper has parseable Python structure, spglib orbit construction, actual elph input discovery, closed q mapping, and per-μ deck writes; output basenames are implementation-defined and bounded sandbox behavior replay is recorded separately")
    ck("coarse_symmetry_compatible", "nosym" not in nls["coarse_scf.in"].get("system",{}) and "noinv" not in nls["coarse_scf.in"].get("system",{}),"coarse SCF keeps symmetry enabled to match irreducible-mesh weight calculation")
    stages=_resolve_run_stages(run)
    observed=[x[0] for x in stages]
    required_order=["dense","coarse","ph","q2r","matdyn","qmap","mu016","mu010"]
    positions=[observed.index(x) if x in observed else -1 for x in required_order]
    ck("scf_dataset_consistency",same_prefix and same_outdir,"dense and coarse SCF reuse the same prefix and normalized outdir")
    ck("lambda_after_ph_in_run",all(x>=0 for x in positions) and positions==sorted(positions) and positions[5]<positions[6]<positions[7],f"recognized declared engine/input sequence={stages}")
    # Plan / resource and declared executable order.
    grids=pv["grids"] if isinstance(pv["grids"],dict) else {}
    ck("plan_grid_match",grids.get("dense_scf_k")==([gd[0],gd[1],gd[2]] if gd else None) and grids.get("coarse_scf_k")==([gc[0],gc[1],gc[2]] if gc else None) and grids.get("q")==cfg["q_grid"],f"plan={grids}; decks={gd},{gc}")
    cost=pv["cost"] if isinstance(pv["cost"],dict) else {}
    if "stages" in cost and isinstance(cost.get("stages"),dict):
        stage_cost=cost["stages"]; total=cost.get("total"); ph_cost=stage_cost.get("ph_dfpt",stage_cost.get("ph")); stage_values=list(stage_cost.values())
    else:
        stage_cost=cost; total=cost.get("total"); ph_cost=cost.get("ph"); stage_values=[cost.get(k) for k in ("dense_scf","coarse_scf","ph","post")]
    finite=all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>0 for x in stage_values+[total,ph_cost])
    sumok=finite and math.isclose(total,sum(stage_values),rel_tol=0,abs_tol=cfg["budget_sum_abs_tolerance"])
    budget_total=cost.get("budget_core_hours",cfg["budget_total_core_hours_max"]) if "stages" in cost else cfg["budget_total_core_hours_max"]
    budget_ph=cost.get("phonon_budget_core_hours",cfg["budget_ph_core_hours_max"]) if "stages" in cost else cfg["budget_ph_core_hours_max"]
    ck("budget_sum_and_limits",sumok and total<=budget_total and ph_cost<=budget_ph and budget_total<=cfg["budget_total_core_hours_max"] and budget_ph<=cfg["budget_ph_core_hours_max"],f"stage estimates={stage_cost}; total={total}; ph={ph_cost}; planning only")
    basis=str(pv["basis"] or "")
    ck("budget_estimate_disclosed",_looks_unmeasured(basis) and ("estimate" in basis.lower() or "planning" in basis.lower() or "估算" in basis or "规划" in basis),basis)
    rat=pv["rationale"] if isinstance(pv["rationale"],dict) else {}
    dense_reason=rat.get("dense_scf_k") or (rat.get("error_direction") if isinstance(rat,dict) else "")
    coarse_reason=rat.get("coarse_scf_k") or rat.get("error_direction") or rat.get("tradeoff")
    q_reason=rat.get("q") or rat.get("error_direction") or rat.get("tradeoff")
    smear_reason=rat.get("degauss") or rat.get("cutoff_smearing")
    uncertainty_data=pv["uncertainty"]
    typed_uncertainty=(isinstance(uncertainty_data,dict) and any(k.endswith("_status") for k in uncertainty_data))
    if typed_uncertainty:
        statuses=[uncertainty_data.get(k) for k in ("dense_k_status","coarse_q_status","interpolation_status","smearing_status")]
        status_ok=all(isinstance(x,str) and x.lower() in {"unresolved","not_measured","unverified","unknown"} for x in statuses)
        explanations=[uncertainty_data.get(k) for k in ("dense_k_note","coarse_q_note","interpolation_note","smearing_note")]
        notes_ok=all(isinstance(x,str) and bool(x.strip()) and _looks_unmeasured(x) for x in explanations)
    else:
        status_ok=all(isinstance(x,str) and bool(x.strip()) for x in (dense_reason,coarse_reason,q_reason,smear_reason))
        notes_ok=all(_looks_unmeasured(x) for x in (dense_reason,coarse_reason,q_reason,smear_reason))
    claim_texts=[dense_reason,coarse_reason,q_reason,smear_reason]
    # Check every explicit legacy and typed axis note independently. An
    # "unknown" note cannot mask a definite statement in a different field.
    claim_texts.extend(rat.get(k) for k in ("error_direction","tradeoff","cutoff_smearing"))
    if isinstance(uncertainty_data,dict):
        claim_texts.extend(uncertainty_data.get(k) for k in ("dense_k_note","coarse_q_note","interpolation_note","smearing_note"))
    no_claims=not any(_has_unverified_error_claim(x) for x in claim_texts if x is not None)
    uncertainty=status_ok and notes_ok and no_claims
    ck("grid_and_smearing_uncertainty_disclosed",uncertainty,"unmeasured dense-k, coarse-q, interpolation and smearing limitations must remain explicitly unresolved; unsupported error-direction or no-extra-error assertions fail")
    declared_order=_ordered_stages(pv["order"])
    seq_ok=declared_order is not None and all(x in declared_order for x in required_order[:6])
    if seq_ok:
        seq_indices=[declared_order.index(x) for x in required_order[:6]]
        seq_ok=seq_indices==sorted(seq_indices)
    ck("run_order",all(x>=0 for x in positions) and positions==sorted(positions),f"recognized engine/input sequence={stages}","L3")
    ck("runner_uses_verified_qe72_chain",pv["native"] and seq_ok,f"declared stages={pv['order']}; QE target={pv['qe']}","L3")
    return emit("PASS" if all(c["passed"] for c in checks) else "FAIL",checks=checks)

if __name__=="__main__": raise SystemExit(main(sys.argv))
