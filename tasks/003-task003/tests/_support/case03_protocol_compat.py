"""Narrow normalization for the published v6 Case 03 protocol layouts."""


def normalize_v6_protocol(protocol, arm_sources, repeats_per_size):
    if not isinstance(protocol, dict):
        raise ValueError("protocol must be an object")
    if protocol.get("scorer_contract_version") not in (None, 6):
        return protocol

    normalized = dict(protocol)
    arm_names = set(arm_sources)
    spec = protocol.get("model_spec")
    spec_arms = spec.get("arms") if isinstance(spec, dict) else None
    declared = protocol.get("representations")
    scored = protocol.get("scored_representations")
    if declared is not None:
        if not isinstance(declared, dict) or set(declared) != arm_names:
            raise ValueError("representations must identify exactly the three scored arms")
        if not isinstance(spec_arms, dict) or set(spec_arms) != arm_names:
            raise ValueError("representations must correspond to the three model_spec arms")
        for arm, source in arm_sources.items():
            item = declared[arm]
            spec_arm = spec_arms[arm]
            if (not isinstance(item, dict) or item.get("scored") is not True
                    or item.get("source_matrix_file") != source or not isinstance(spec_arm, dict)):
                raise ValueError(f"representation identity is invalid for {arm}")
            if "source_matrix_file" in spec_arm and spec_arm["source_matrix_file"] != source:
                raise ValueError(f"model_spec source_matrix_file is invalid for {arm}")
        if scored is not None:
            if (not isinstance(scored, list) or any(type(arm) is not str for arm in scored)
                    or len(scored) != len(arm_names) or len(set(scored)) != len(arm_names)
                    or set(scored) != arm_names):
                raise ValueError("scored_representations conflicts with representations")
        normalized["scored_representations"] = list(arm_sources)
    elif scored is not None:
        if (not isinstance(scored, list) or any(type(arm) is not str for arm in scored)
                or len(scored) != len(arm_names) or len(set(scored)) != len(arm_names)
                or set(scored) != arm_names):
            raise ValueError("scored_representations must list each required arm exactly once")

    design = protocol.get("comparison_design")
    if isinstance(design, dict):
        if design.get("reference_arm") != "mechanistic":
            raise ValueError("comparison_design reference_arm must be mechanistic")
        comparators = design.get("comparators")
        expected_comparators = arm_names - {"mechanistic"}
        if (not isinstance(comparators, list) or any(type(arm) is not str for arm in comparators)
                or len(comparators) != len(expected_comparators)
                or len(set(comparators)) != len(expected_comparators)
                or set(comparators) != expected_comparators):
            raise ValueError("comparison_design comparators must identify no_ts and fingerprint exactly once")
        optional_checks = {
            "paired_repeats": (type(design.get("paired_repeats")) is bool
                               and design.get("paired_repeats") is True),
            "paired_repeats_per_size": (type(design.get("paired_repeats_per_size")) is int
                                         and design.get("paired_repeats_per_size") == repeats_per_size),
            "same_sampled_training_indices_across_representations": (
                type(design.get("same_sampled_training_indices_across_representations")) is bool
                and design.get("same_sampled_training_indices_across_representations") is True),
            "same_frozen_test_set_across_representations_and_repeats": (
                type(design.get("same_frozen_test_set_across_representations_and_repeats")) is bool
                and design.get("same_frozen_test_set_across_representations_and_repeats") is True),
            "difference_definition": design.get("difference_definition") == "comparator_mae_minus_mechanistic_mae",
            "interval_scope": design.get("interval_scope") == "training_subset_repeat_conditional_on_frozen_test_set",
            "metrics": (isinstance(design.get("metrics"), list)
                        and all(type(metric) is str for metric in design["metrics"])
                        and {"mae_kcal_mol", "rmse_kcal_mol"}.issubset(set(design["metrics"]))),
        }
        for field, valid in optional_checks.items():
            if field in design and not valid:
                raise ValueError(f"comparison_design.{field} conflicts with the paired frozen-test comparison")
        for field in ("same_sampled_training_indices_across_representations",
                      "same_frozen_test_set_across_representations_and_repeats"):
            if field in design and field in protocol and design[field] != protocol[field]:
                raise ValueError(f"comparison_design.{field} conflicts with the top-level declaration")
        normalized["comparison_design"] = "controlled_representation"
    elif type(design) is str and design in ("controlled_representation", "model_selection_combination"):
        pass
    else:
        raise ValueError("comparison_design must use a registered value or supported structured declaration")
    return normalized
