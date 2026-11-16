#!/usr/bin/env bash
set -euo pipefail
exec python3 - <<'CCB_CASE06_CLIENT'
#!/usr/bin/env python3
"""Public candidate client for the Case06 staged runner API."""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, "/app/environment")

FINAL = Path("/app/final")
CHANNELS = ("overall", "ADP", "IMP")
THRESHOLD = 0.02


def evaluate_prediction(prediction, prior, observed):
    expected = prediction.get("expected_class")
    if expected not in {"REMAINS_ABOVE_2_PERCENT", "AT_OR_BELOW_2_PERCENT"}:
        raise ValueError("prediction expected_class is unsupported")
    if observed is None:
        return {"ratio_followup_over_prior": None, "ratio_undefined_reason": "PENDING_VALUE",
                "prediction_supported": None, "prediction_status": "INDETERMINATE",
                "expected_class": expected}
    if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(float(observed)):
        raise ValueError("observed follow-up change must be finite")
    observed_class = "AT_OR_BELOW_2_PERCENT" if observed <= THRESHOLD else "REMAINS_ABOVE_2_PERCENT"
    metric = prediction.get("metric")
    if prior is not None and not isinstance(prior, bool) and isinstance(prior, (int, float)) and prior > 0:
        if metric not in (None, "followup_target_relative_change_over_prior_axis_pair"):
            raise ValueError("positive-prior prediction metric does not match target")
        maximum_ratio = prediction.get("maximum_ratio")
        if (isinstance(maximum_ratio, bool) or not isinstance(maximum_ratio, (int, float))
                or not math.isfinite(float(maximum_ratio)) or maximum_ratio <= 0):
            raise ValueError("maximum_ratio must be finite and positive")
        ratio = float(observed) / float(prior)
        supported = ratio <= float(maximum_ratio) and observed_class == expected
        return {"ratio_followup_over_prior": ratio, "ratio_undefined_reason": None,
                "prediction_supported": supported, "prediction_status": "SUPPORTED" if supported else "REFUTED",
                "expected_class": expected}
    if prior == 0:
        if metric != "followup_target_threshold_class":
            raise ValueError("zero-prior prediction must use threshold-class metric")
        threshold = prediction.get("threshold")
        if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                or not math.isfinite(float(threshold))
                or not math.isclose(float(threshold), THRESHOLD, rel_tol=1e-10, abs_tol=1e-14)):
            raise ValueError("threshold must be the registered 2% value")
        supported = observed_class == expected
        return {"ratio_followup_over_prior": None, "ratio_undefined_reason": "ZERO_PRIOR_CHANGE",
                "prediction_supported": supported, "prediction_status": "SUPPORTED" if supported else "REFUTED",
                "expected_class": expected}
    raise ValueError("sealed target must have a defined positive or zero prior change")


def canonical(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode())


def row(pair, channel, doping, direction):
    return next(r for r in pair["components"] if (r["channel"], r["doping_cm-3"], r["direction"]) ==
                (channel, doping, direction))


def compare(old, new):
    concentrations = [-1.99e14, -2.20e15, -1.72e16, -1.86e17, -1.46e18, -4.39e18]
    components = []
    for channel in CHANNELS:
        for doping in concentrations:
            for idx, direction in enumerate(("xx", "yy", "zz")):
                before = old["channels_cm2_per_Vs"][channel][concentrations.index(doping)][idx]
                after = new["channels_cm2_per_Vs"][channel][concentrations.index(doping)][idx]
                if isinstance(before, bool) or isinstance(after, bool) or not isinstance(before,(int,float)) or not isinstance(after,(int,float)):
                    raise ValueError("comparison mobility must be numeric")
                if not math.isfinite(before) or not math.isfinite(after):
                    relative, pending_reason = None, "NONFINITE_INPUT"
                elif after == 0:
                    relative, pending_reason = None, "ZERO_DENOMINATOR"
                else:
                    relative, pending_reason = abs(before-after)/abs(after), None
                row={"channel":channel,"doping_cm-3":doping,"direction":direction,
                    "old":before if math.isfinite(before) else None,"new":after if math.isfinite(after) else None,
                    "relative_change":relative,"passes_2percent":None if relative is None else relative<=.02}
                if pending_reason is not None: row["pending_reason"]=pending_reason
                components.append(row)
    defined=[r for r in components if r["relative_change"] is not None]
    pending=[r for r in components if r["relative_change"] is None]
    failed=[r for r in defined if not r["passes_2percent"]]
    limiting=max(defined,key=lambda x:x["relative_change"]) if defined else None
    status="FAIL" if failed else "PENDING" if pending else "PASS"
    return {"status":status,"relative_change_formula":"abs(old-new)/abs(new)","threshold":.02,
      "component_count":len(components),"defined_count":len(defined),"pending_count":len(pending),
      "max_relative_change":None if limiting is None else limiting["relative_change"],
      "limiting_component":limiting,"components":components}


def roundrow(r):
    row={k:r.get(k) for k in ("channel","doping_cm-3","direction","old","new","relative_change","passes_2percent")}
    if r.get("pending_reason") is not None: row["pending_reason"]=r["pending_reason"]
    return row


def axis_facts(pair, pair_ids):
    rows=pair["components"]; failed=[r for r in rows if r.get("passes_2percent") is False]
    pending=[r for r in rows if r.get("relative_change") is None]
    defined=[r for r in rows if r.get("relative_change") is not None]
    limiter=max(defined,key=lambda r:r["relative_change"]) if defined else None
    return {"parent_pair":pair_ids,"component_count":len(rows),"defined_count":len(defined),"pending_count":len(pending),
      "status":pair["status"],"exceedance_count":len(failed),
      "exceedances_by_channel":{c:sum(r["channel"]==c for r in failed) for c in CHANNELS},
      "maximum":None if limiter is None else roundrow(limiter),"all_exceedances":[roundrow(r) for r in failed],
      "pending_components":[roundrow(r) for r in pending]}


def private_pair(parent, control, run_id):
    pair = compare(parent, control)
    pair["limiting_component"] = max((r for r in pair["components"] if r.get("relative_change") is not None),
                                     key=lambda r:r["relative_change"], default=None)
    old, new = parent["effective_fd_cutoffs_eV"], control["effective_fd_cutoffs_eV"]
    if new == old: relation="UNCHANGED"
    elif new[0]<=old[0] and new[1]>=old[1]: relation="EXPANDED"
    elif new[0]>=old[0] and new[1]<=old[1]: relation="NARROWED"
    else: relation="INCOMPARABLE"
    pair.update({"effective_window_old_eV":old,"effective_window_new_eV":new,
        "same_factor":parent["actual_factor"]==control["actual_factor"],
        "same_mesh":parent["actual_mesh"]==control["actual_mesh"],
        "comparison_status":pair["status"],"interval_relation":relation,
        "parent_run_id":run_id})
    return pair


def build_typed(latest, plan, observed, private, settings):
    axes={"coupled_fit_mesh":axis_facts(latest["mesh_pair"],latest["mesh_pair_ids"]),
          "effective_window":axis_facts(latest["window_pair"],latest["window_pair_ids"])}
    masking={}
    for name,pair in (("coupled_fit_mesh",latest["mesh_pair"]),("effective_window",latest["window_pair"])):
        by={(r["channel"],r["doping_cm-3"],r["direction"]):r for r in pair["components"]}; examples=[]
        for n in sorted({r["doping_cm-3"] for r in pair["components"]}):
            for direction in ("xx","yy","zz"):
                overall=by[("overall",n,direction)]; mechanisms=[by[(c,n,direction)] for c in ("ADP","IMP")]
                if overall["passes_2percent"] and any(not r["passes_2percent"] for r in mechanisms):
                    examples.append({"doping_cm-3":n,"direction":direction,"overall_relative_change":overall["relative_change"],"overall_passes":True,
                        "mechanism_failures":[{"channel":r["channel"],"relative_change":r["relative_change"]} for r in mechanisms if not r["passes_2percent"]]})
        masking[name]=examples
    target={"channel":plan["limiting_mechanism"],"doping_cm-3":plan["limiting_doping_cm-3"],"direction":plan["limiting_direction"]}
    failing=[x for x in ("coupled_fit_mesh","effective_window") if axes[x]["status"]=="FAIL" and axes[x]["maximum"] is not None]
    available=[x for x in ("coupled_fit_mesh","effective_window") if axes[x]["maximum"] is not None]
    next_axis=max(failing,key=lambda x:axes[x]["maximum"]["relative_change"]) if failing else (max(available,key=lambda x:axes[x]["maximum"]["relative_change"]) if available else "coupled_fit_mesh")
    setting=dict(settings[next_axis]); next_setting={"factor":math.ceil(setting["factor"]*1.5) if next_axis=="coupled_fit_mesh" else setting["factor"],
        "fd_tol":setting["fd_tol"] if next_axis=="coupled_fit_mesh" else setting["fd_tol"]/10}
    prior=observed["prior_relative_change"]; after=observed["followup_relative_change"]
    p={"component_count":len(private["components"]),"maximum":roundrow(private["limiting_component"]),
       "exceedance_count":sum(not r["passes_2percent"] for r in private["components"]),
       "exceedances_by_channel":{c:sum(not r["passes_2percent"] for r in private["components"] if r["channel"]==c) for c in CHANNELS},
       "effective_window_old_eV":private["effective_window_old_eV"],"effective_window_new_eV":private["effective_window_new_eV"],
       "same_factor":private["same_factor"],"same_mesh":private["same_mesh"],
       "comparison_status":private["comparison_status"],"interval_relation":private["interval_relation"],
       "parent_run_id":private["parent_run_id"]}
    p["interpretation_facts"]={"observed_diagnosis":"DEMONSTRATED_NOT_CONVERGED" if p["comparison_status"]=="FAIL" else "INSUFFICIENT_EVIDENCE" if p["comparison_status"]=="PENDING" else "WITHIN_2_PERCENT",
        "comparison_scope":"SAME_EFFECTIVE_WINDOW_CONTROL" if p["interval_relation"]=="UNCHANGED" else "EFFECTIVE_WINDOW_ONLY",
        "interval_relation":p["interval_relation"],"limiting_condition":roundrow(private["limiting_component"]),
        "policy_committed_before_setting_selection":True,"facts_revealed_after_run_for_interpretation":True}
    return {"diagnosis_outcome":latest["diagnosis_outcome"],"axes":axes,
      "overall_masking":{x:{"count":len(rows),"same_condition_examples":rows} for x,rows in masking.items()},
      "mechanism_transport_note":"combined_rates",
      "attribution":{"coupled_fit_mesh_only":True,"pure_integration_mesh_claim":False,"window_pair_ids":latest["window_pair_ids"],
        "absolute_accuracy_claim":False,"scope":"tested_settings_budget"},
      "followup":{"axis":plan["selected_axis"],"target":target,"parent_pair":plan["parent_pair"],"prior_relative_change":prior,
        "observed_relative_change":after,"ratio_followup_over_prior":observed["ratio_followup_over_prior"],
        "ratio_undefined_reason":observed["ratio_undefined_reason"],"prediction":plan["prediction"],
        "prediction_supported":observed["prediction_supported"],"prediction_status":observed["prediction_status"],
        "observed_class":None if after is None else "AT_OR_BELOW_2_PERCENT" if after<=.02 else "REMAINS_ABOVE_2_PERCENT"},
      "next_action":{"axis":next_axis,"limiting_component":axes[next_axis]["maximum"],"parent_pair":axes[next_axis]["parent_pair"],
        "parent_factor":setting["factor"],"parent_fd_tol":setting["fd_tol"],"minimum_factor_ratio":1.5 if next_axis=="coupled_fit_mesh" else None,
        "reason_code":"REFINE_LATEST_LIMITING_AXIS" if failing else "RECHECK_GLOBAL_MAXIMUM","requested_setting":next_setting},
      "private_control":p}


def main():
    import case06_rpc
    FINAL.mkdir(parents=True,exist_ok=True)
    matrix={"schema":"case06-v2-matrix-plan/v1","runs":[
        {"run_id":"mesh-1","factor":3,"fd_tol":.1,"workers":2},
        {"run_id":"mesh-2","factor":5,"fd_tol":.1,"workers":2},
        {"run_id":"mesh-3","factor":7,"fd_tol":.1,"workers":2},
        {"run_id":"window-2","factor":7,"fd_tol":.01,"workers":2}]}
    first=case06_rpc.call("init",{"matrix":matrix});
    if first.get("phase")!="INITIALIZED": raise RuntimeError("trusted session did not initialize")
    phase=case06_rpc.call("run-four")
    facts=phase["facts"]; maximum=facts["global_maximum_108"]; target=maximum["component"]
    axis=maximum["axis"]
    prediction=(
      {"metric":"followup_target_threshold_class","threshold":.02,
       "expected_class":"AT_OR_BELOW_2_PERCENT"} if target["relative_change"]==0 else
      {"metric":"followup_target_relative_change_over_prior_axis_pair","maximum_ratio":.9,
       "expected_class":"REMAINS_ABOVE_2_PERCENT" if target["relative_change"]>.02 else "AT_OR_BELOW_2_PERCENT"})
    plan={"schema":"case06-v2-followup-plan/v1","four_run_receipt_ids":["mesh-1","mesh-2","mesh-3","window-2"],
      "selected_axis":axis,"limiting_doping_cm-3":target["doping_cm-3"],"limiting_mechanism":target["channel"],
      "limiting_direction":target["direction"],"observed_relative_change":target["relative_change"],
      "prediction":prediction,
      "budget_seconds":180,"budget_peak_rss_bytes":12*1024**3,
      "parent_pair":["mesh-3","followup-5"] if axis=="coupled_fit_mesh" else ["window-2","followup-5"],
      "requested_setting":{"factor":math.ceil(phase["facts"]["runs"]["mesh-3"]["actual_factor"]*1.5) if axis=="coupled_fit_mesh" else phase["facts"]["runs"]["window-2"]["actual_factor"],
        "fd_tol":phase["facts"]["runs"]["mesh-3"]["actual_fd_tol"] if axis=="coupled_fit_mesh" else phase["facts"]["runs"]["window-2"]["actual_fd_tol"]/10},
      "discriminating_hypothesis":"The selected numerical axis is the dominant source of the limiting mobility change.",
      "expected_discriminator":("The follow-up target will remain at or below the 2% threshold." if target["relative_change"]==0 else "The limiting component's follow-up relative change will fall by at least ten percent.")}
    sealed=case06_rpc.call("seal",{"plan":plan});
    if sealed.get("phase")!="SEALED": raise RuntimeError("follow-up plan was not sealed")
    after=case06_rpc.call("run-followup")
    follow=after["followup5"]
    parent_id="mesh-3" if axis=="coupled_fit_mesh" else "window-2"
    pair=compare(phase["facts"]["runs"][parent_id],follow)
    priorpair=phase["facts"]["comparisons"]["mesh-2_to_mesh-3" if axis=="coupled_fit_mesh" else "mesh-3_to_window-2"]
    before=row(priorpair,target["channel"],target["doping_cm-3"],target["direction"])["relative_change"]
    changed=row(pair,target["channel"],target["doping_cm-3"],target["direction"])["relative_change"]
    prediction=plan["prediction"]
    evaluated=evaluate_prediction(prediction,before,changed)
    actual_class=None if changed is None else "AT_OR_BELOW_2_PERCENT" if changed<=.02 else "REMAINS_ABOVE_2_PERCENT"
    observation={"prior_relative_change":before,"followup_relative_change":changed,
      "ratio_followup_over_prior":evaluated["ratio_followup_over_prior"],
      "ratio_undefined_reason":evaluated["ratio_undefined_reason"],
      "prediction_supported":evaluated["prediction_supported"],"prediction_status":evaluated["prediction_status"],
      "expected_class":evaluated["expected_class"]}
    policy={"schema":"case06-v2-private-control-policy/v1","axis":"effective_window",
      "response_rule":"compare_all_54_against_same_mesh_parent_and_explain_scope"}
    control_result=case06_rpc.call("private-control",{"policy":policy})
    control=control_result["private_control_facts"]
    runmap={**phase["facts"]["runs"],"followup-5":follow}
    if after.get("window_match"): runmap["window-match-3"]=after["window_match"]
    runmap["private-control"]=control
    challenge_parent="window-match-3" if "window-match-3" in runmap else "followup-5"
    private=private_pair(runmap[challenge_parent],control,challenge_parent)
    if axis=="coupled_fit_mesh":
        mesh_ids=["mesh-3","followup-5"]
        window_ids=["followup-5","window-match-3"]
    else:
        mesh_ids=["mesh-2","mesh-3"]
        window_ids=["window-2","followup-5"]
    if "window-match-3" in runmap:
        window_label="followup-5_to_window-match-3"
    elif axis=="effective_window":
        window_label="window-2_to_followup-5"
    else:
        window_label="mesh-3_to_window-2"
    old_cutoffs=runmap[window_ids[0]]["effective_fd_cutoffs_eV"]
    new_cutoffs=runmap[window_ids[1]]["effective_fd_cutoffs_eV"]
    latest={"mesh_pair_ids":mesh_ids,"mesh_pair":compare(runmap[mesh_ids[0]],runmap[mesh_ids[1]]),
      "window_pair_ids":window_ids,"window_pair":compare(runmap[window_ids[0]],runmap[window_ids[1]]),
      "window_pair_label":window_label,"window_cutoffs_old_eV":old_cutoffs,"window_cutoffs_new_eV":new_cutoffs,
      "effective_window_expanded":new_cutoffs[0]<=old_cutoffs[0] and new_cutoffs[1]>=old_cutoffs[1] and new_cutoffs!=old_cutoffs}
    latest["diagnosis_outcome"]=("DEMONSTRATED_NOT_CONVERGED" if latest["mesh_pair"]["status"]=="FAIL" or latest["window_pair"]["status"]=="FAIL" else
      "INSUFFICIENT_EVIDENCE" if latest["mesh_pair"]["status"]=="PENDING" or latest["window_pair"]["status"]=="PENDING" else "CONVERGED_WITHIN_TESTED_BUDGET")
    settings={"coupled_fit_mesh":{"factor":runmap[mesh_ids[1]]["actual_factor"],"fd_tol":runmap[mesh_ids[1]]["actual_fd_tol"]},
      "effective_window":{"factor":runmap[window_ids[1]]["actual_factor"],"fd_tol":runmap[window_ids[1]]["actual_fd_tol"]}}
    expected=build_typed(latest,plan,observation,private,settings)
    next_target=expected["next_action"]["limiting_component"]
    next_prediction=({"metric":"followup_target_threshold_class","threshold":.02,"expected_class":"AT_OR_BELOW_2_PERCENT"}
      if next_target is not None and next_target["relative_change"]==0 else
      {"maximum_ratio":.9,"expected_class":"AT_OR_BELOW_2_PERCENT" if next_target is not None and next_target["relative_change"]<=.02 else "REMAINS_ABOVE_2_PERCENT"})
    next_prediction.update({"axis":expected["next_action"]["axis"],
      "parent_pair":[expected["next_action"]["parent_pair"][1],"proposed-followup"],
      "target":copy.deepcopy(next_target)})
    report={"schema":"case06-v2-typed-scientific-report/v1",**{k:copy.deepcopy(expected[k]) for k in
      ("diagnosis_outcome","axes","overall_masking","mechanism_transport_note","attribution","followup","next_action","private_control")},
      "next_action_prediction":next_prediction,
      "narrative":"The latest pair identifies the limiting tested condition; findings apply only to tested settings and budget."}
    response={"schema":"case06-v2-private-control-response/v1",**{k:copy.deepcopy(v) for k,v in expected["private_control"].items()}}
    response.pop("interpretation_facts")
    response["interpretation_facts"]=copy.deepcopy(expected["private_control"]["interpretation_facts"])
    canonical(FINAL/"report.json",report); canonical(FINAL/"private-control-response.json",response)
    mesh=expected["axes"]["coupled_fit_mesh"]; window=expected["axes"]["effective_window"]
    private_summary=expected["private_control"]
    next_action=expected["next_action"]
    mesh_mask=expected["overall_masking"]["coupled_fit_mesh"]["count"]
    window_mask=expected["overall_masking"]["effective_window"]["count"]
    markdown=("# Case06 numerical convergence\n\n"
      f"**Outcome:** `{latest['diagnosis_outcome']}`. The classification uses the latest valid adjacent pair on each axis.\n\n"
      "| Axis | Pair | Status | Exceedances / 54 | Maximum relative change |\n|---|---|---:|---:|---:|\n"
      f"| Coupled fit/mesh | {', '.join(mesh['parent_pair'])} | {mesh['status']} | {mesh['exceedance_count']} | {mesh['maximum']['relative_change']:.6g} ({mesh['maximum']['channel']}, {mesh['maximum']['doping_cm-3']:g} cm⁻³, {mesh['maximum']['direction']}) |\n"
      f"| Effective window | {', '.join(window['parent_pair'])} | {window['status']} | {window['exceedance_count']} | {window['maximum']['relative_change']:.6g} ({window['maximum']['channel']}, {window['maximum']['doping_cm-3']:g} cm⁻³, {window['maximum']['direction']}) |\n\n"
      f"The sealed follow-up targeted `{plan['selected_axis']}` at {plan['limiting_mechanism']} / {plan['limiting_doping_cm-3']:g} cm⁻³ / {plan['limiting_direction']}. Its relative change moved from {observation['prior_relative_change']:.6g} to {observation['followup_relative_change']:.6g}; the stated prediction was {'supported' if observation['prediction_supported'] else 'not supported'}.\n\n"
      f"The evaluator-selected private window control compared {private_summary['component_count']} components and classified {private_summary['comparison_status']} ({private_summary['interval_relation']}); maximum change was {private_summary['maximum']['relative_change']:.6g}.\n\n"
      f"Overall transport masks a mechanism exceedance at {mesh_mask} same-condition entries on the coupled fit/mesh axis and {window_mask} entries on the effective-window axis. Overall mobility is rebuilt from combined rates; ADP and IMP mobility values are not additive.\n\n"
      f"Next numerical action: refine `{next_action['axis']}` from {', '.join(next_action['parent_pair'])}, focusing on {next_action['limiting_component']['channel']} / {next_action['limiting_component']['doping_cm-3']:g} cm⁻³ / {next_action['limiting_component']['direction']}.\n\n"
      "All conclusions apply to the tested settings and tested budget. The coupled fit/mesh axis changes fitting and actual mesh together, so its discrepancy cannot be attributed to integration mesh alone; no absolute-accuracy or asymptotic-convergence claim is made.\n")
    (FINAL/"report.md").write_text(markdown,encoding="utf-8")
    result=case06_rpc.call("finalize",{"report":report,"response":response})
    if (not result.get("session_id") or not result.get("facts_sha256")
            or result.get("evaluator_disposition") not in {
                "PASS_1_HOST_EVALUATOR_SELF_TEST","FAIL_0_TYPED_FACT_CONTRADICTION",
                "FAIL_0_TYPED_INTERPRETATION_INCOMPLETE"}):
        raise RuntimeError("trusted finalization did not return sealed evaluator facts")
    return 0


if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"Case06 candidate failed: {type(exc).__name__}: {exc}",file=sys.stderr)
        raise
CCB_CASE06_CLIENT
