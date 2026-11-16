"""Extract the cited TNEP measurements from the author-only official PDFs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from pypdf import PdfReader


SOURCES = {
    "official_main_article.pdf": "321617c376e0ba91600b4b83f4e377aa8c001b4bcbe3c0648ab248b61b6d5a9f",
    "official_supplementary_information.pdf": "50529429377166ee34b3addce4b3256cae17e65a47492fabc4cd39a40bb83834",
}
ARTICLE_CITATION = (
    "Xu et al., Journal of Chemical Theory and Computation 2024, 20, 3273–3284, "
    "DOI 10.1021/acs.jctc.3c01343 (published ACS version; Supporting Information dated March 19, 2024)"
)


def fail(message: str) -> None:
    raise SystemExit(message)


def read_pdf(path: Path, expected_sha: str) -> list[str]:
    if not path.is_file():
        fail(f"Missing source PDF: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_sha:
        fail(f"Source PDF SHA-256 mismatch: {path.name}")
    try:
        pages = PdfReader(str(path)).pages
        result = [page.extract_text() or "" for page in pages]
    except Exception as exc:
        fail(f"Cannot extract source PDF {path.name}: {exc}")
    if not any(result):
        fail(f"Source PDF has no extractable text: {path.name}")
    return result


def page_containing(pages: list[str], needle: str) -> tuple[int, str]:
    key = compact(needle).casefold()
    for i, text in enumerate(pages):
        if key in compact(text).casefold():
            return i, text
    fail(f"Could not locate source text: {needle}")


def section(text: str, start: str, end: str) -> str:
    text, start, end = compact(text), compact(start), compact(end)
    a = text.find(start)
    if a < 0:
        fail(f"Could not locate table heading: {start}")
    b = text.find(end, a + len(start))
    return text[a:] if b < 0 else text[a:b]


def compact(text: str) -> str:
    text = re.sub(r"\s+", " ", text.replace("ﬃ", "ffi").replace("ﬀ", "ff")).strip()
    text = re.sub(r"\bT\s+able\b", "Table", text)
    text = re.sub(r"\bF\s+or\b", "For", text)
    text = re.sub(r"\bW\s+e\b", "We", text)
    text = re.sub(r"\bT\s+r\b", "Tr", text)
    # pypdf 5.x emits chemical subscripts as independent text runs.
    text = re.sub(r"\bH\s+(\d+)\s+O\s+(\d+)\s*\+", r"H\1O\2+", text)
    text = re.sub(r"\(H\s+(\d+)\s+O\)\s+(\d+)", r"(H\1O)\2", text)
    text = re.sub(r"\bH\s+(\d+)\s+O\b", r"H\1O", text)
    text = re.sub(r"\bbohr\s+3\b", "bohr3", text)
    return re.sub(r"(?<=[0-9A-Za-z])\s+([−-])\s*(\d+)", r"\1\2", text)


def table_row(block: str, label_pattern: str, next_labels: list[str]) -> str:
    match = re.search(label_pattern, block, flags=re.IGNORECASE)
    if not match:
        fail(f"Could not locate row matching {label_pattern!r}")
    start = match.end()
    ends = []
    for label in next_labels:
        found = re.search(label, block[start:], flags=re.IGNORECASE)
        if found:
            ends.append(start + found.start())
    end = min(ends) if ends else len(block)
    return block[start:end]


def source_numbers(text: str) -> list[float]:
    """Read ordinary and scientific-notation numbers from extracted PDF text."""
    normalized = text.replace("−", "-").replace("–", "-").replace("×", "x")
    pattern = re.compile(r"(?<![\w.])(?:\d+(?:\.\d*)?|\.\d+)(?:\s*x\s*10\s*\^?\s*-?\s*\d+)?%?")
    values: list[float] = []
    for item in pattern.findall(normalized):
        token = item.rstrip("%")
        if "x" in token:
            mantissa, exponent = re.split(r"\s*x\s*10\s*\^?\s*", token)
            values.append(float(mantissa) * 10 ** int(exponent.replace(" ", "")))
        else:
            values.append(float(token))
    return values


def printed_page(text: str, fallback: int) -> str:
    tail = [line.strip() for line in text.splitlines()[-5:] if line.strip()]
    for line in reversed(tail):
        if re.fullmatch(r"\d+", line):
            return line
    return str(fallback)


def add_value(values: list[dict], table: str, cell: str, value: float,
              units: str, provenance: str) -> None:
    if not math.isfinite(value):
        fail(f"Non-finite value extracted for {table}/{cell}")
    values.append({"table": table, "cell": cell, "value": value,
                   "units": units, "provenance": provenance})


def parse_table(main: list[str], page_index: int, heading: str, ending: str,
                table_name: str, systems: list[tuple[str, str]],
                units_for_column: list[str], values: list[dict],
                provenance_label: str) -> None:
    page = compact(main[page_index])
    block = section(page, compact(heading), compact(ending))
    header = re.search(r"System\s+RMSE\s+RRMSE", block, flags=re.IGNORECASE)
    if not header:
        fail(f"Could not locate column headings in {table_name}")
    block = block[header.end():]
    normalization_phrase = (r"dipole moment is given per ([A-Za-z ]+)\." if table_name == "Table 1"
                            else r"χ/ρ is given per ([A-Za-z ]+)\.")
    normalization = re.search(normalization_phrase, block, flags=re.IGNORECASE)
    if not normalization:
        fail(f"Could not locate the liquid-water normalization footnote in {table_name}")
    water_entity = normalization.group(1).strip()
    labels = [pattern for _, pattern in systems]
    if table_name == "Table 1":
        suffixes, source_columns = ("rmse", "rrmse"), (0, 1)
    else:
        suffixes, source_columns = ("diag rmse", "offdiag rmse"), (0, 2)
    for display, label in systems:
        row = table_row(block, label, [p for p in labels if p != label])
        nums = source_numbers(row)
        if len(nums) <= max(source_columns):
            fail(f"Incomplete {table_name} row for {display}: {row!r}")
        for column, suffix, unit in zip(source_columns, suffixes, units_for_column):
            if display == "liquid water":
                unit = f"{unit} per {water_entity}"
            add_value(values, table_name, f"{display} {suffix}", nums[column], unit,
                      f"{ARTICLE_CITATION}, {provenance_label} (PDF p. {page_index + 1})")


def normalized_table_row(block: str, row_name: str) -> list[float]:
    # PDF text extraction separates subscripts and superscripts from the row label.
    text = compact(block)
    if row_name == "rRc":
        pattern = r"r\s*R\s*c\s*\(Å\)\s*([^A-Za-z]+?)(?=r\s*A\s*c\s*\(Å\))"
    elif row_name == "rAc":
        pattern = r"r\s*A\s*c\s*\(Å\)\s*([^A-Za-z]+?)(?=n\s*R\s*max)"
    elif row_name == "nRmax":
        pattern = r"n\s*R\s*max\s*([^A-Za-z]+?)(?=n\s*A\s*max)"
    elif row_name == "nAmax":
        pattern = r"n\s*A\s*max\s*([^A-Za-z]+?)(?=l\s*3b)"
    else:
        pattern = rf"{re.escape(row_name)}\s+([^A-Za-z]+?)(?=\s*(?:λ|N[a-zA-Z]|r\s*[RA]\s*c|n\s*[RA]\s*max|l\s*3b|Table S\d)|$)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        fail(f"Could not parse {row_name} values from source table")
    return source_numbers(match.group(1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).with_name("source"))
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        fail("Output must be empty; refusing to overwrite an existing submission.")

    main_pdf = args.source_dir / "official_main_article.pdf"
    si_pdf = args.source_dir / "official_supplementary_information.pdf"
    article = read_pdf(main_pdf, SOURCES[main_pdf.name])
    si = read_pdf(si_pdf, SOURCES[si_pdf.name])
    values: list[dict] = []

    t1_page, _ = page_containing(article, "Table 1. RMSEs")
    parse_table(article, t1_page, "Table 1.", "Figure 2.", "Table 1",
                [("H2O", r"(?<![\w)])H2O(?![\w)])"),
                 ("(H2O)2", r"\(H2O\)2"),
                 ("H5O2+", r"H5O2\s*\+"),
                 ("liquid water", r"liquid water")],
                ["e·bohr", "%"], values, "Table 1")

    t2_page, _ = page_containing(article, "Table 2. RMSEs")
    parse_table(article, t2_page, "Table 2.", "Figure 3.", "Table 2",
                [("H2O", r"(?<![\w)])H2O(?![\w)])"),
                 ("(H2O)2", r"\(H2O\)2"),
                 ("H5O2+", r"H5O2\s*\+"),
                 ("liquid water", r"liquid water")],
                ["bohr^3", "bohr^3"], values, "Table 2")

    # The QM7B measurements are reported in the main text rather than a table.
    qm_page, qm_text = page_containing(article, "As a further test, we constructed a TNEP polarizability")
    qm_compact = compact(qm_text).replace("−", "-")
    def measured(pattern: str, label: str) -> float:
        match = re.search(pattern, qm_compact, flags=re.IGNORECASE)
        if not match:
            fail(f"Could not extract {label} from the article text")
        nums = source_numbers(match.group(1))
        if not nums:
            fail(f"No numeric value for {label}")
        return nums[0]
    add_value(values, "QM7B", "dipole rmse per atom",
              measured(r"validation set of (.*?e·bohr atom-1)", "QM7B dipole RMSE"),
              "e·bohr/atom", f"{ARTICLE_CITATION}, Sec. 3.1 (PDF p. {qm_page + 1})")
    add_value(values, "QM7B", "alpha diag rmse per atom",
              measured(r"validation set are (.*?) bohr3 atom-1", "QM7B diagonal alpha RMSE"),
              "bohr^3/atom", f"{ARTICLE_CITATION}, Sec. 3.2 (PDF p. {qm_page + 1})")
    alpha_pair = re.search(r"validation set are ([0-9.]+ × 10-[0-9]+) bohr3 atom-1 and ([0-9.]+ × 10-[0-9]+) bohr3 atom-1", qm_compact)
    if not alpha_pair:
        fail("Could not extract the two QM7B alpha RMSE values from the article text")
    alpha_offdiag = source_numbers(alpha_pair.group(2))
    add_value(values, "QM7B", "alpha offdiag rmse per atom",
              alpha_offdiag[0],
              "bohr^3/atom", f"{ARTICLE_CITATION}, Sec. 3.2 (PDF p. {qm_page + 1})")
    add_value(values, "QM7B", "dipole r2",
              measured(r"score for the validation set of about ([0-9]+\.[0-9]+)", "QM7B dipole R2"),
              "dimensionless", f"{ARTICLE_CITATION}, Sec. 3.1 (PDF p. {qm_page + 1})")

    s1_i, s1_text = page_containing(si, "Table S1:")
    s1_block = section(s1_text, "Table S1:", "Table S2:")
    s1_neurons = normalized_table_row(s1_block, "Nneu")
    s1_rr = normalized_table_row(s1_block, "rRc")
    s1_ar = normalized_table_row(s1_block, "rAc")
    if len(s1_neurons) < 5 or len(s1_rr) < 1 or len(s1_ar) < 1:
        fail("Table S1 rows did not yield the expected source columns")
    s1_page = printed_page(s1_text, s1_i + 1)
    add_value(values, "Table S1", "H2O Nneu", s1_neurons[0], "neurons",
              f"{ARTICLE_CITATION}, Supporting Information Table S1 (p. {s1_page})")
    add_value(values, "Table S1", "QM7B Nneu", s1_neurons[4], "neurons",
              f"{ARTICLE_CITATION}, Supporting Information Table S1 (p. {s1_page})")
    add_value(values, "Table S1", "rRc", s1_rr[0], "Å",
              f"{ARTICLE_CITATION}, Supporting Information Table S1 (p. {s1_page})")
    add_value(values, "Table S1", "rAc", s1_ar[0], "Å",
              f"{ARTICLE_CITATION}, Supporting Information Table S1 (p. {s1_page})")

    s2_i, s2_text = page_containing(si, "Table S2:")
    s2_block = section(s2_text, "Table S2:", "Table S3:")
    s2_neurons = normalized_table_row(s2_block, "Nneu")
    s2_pop = normalized_table_row(s2_block, "Npop")
    s2_gen = normalized_table_row(s2_block, "Ngen")
    s2_rn = normalized_table_row(s2_block, "nRmax")
    s2_an = normalized_table_row(s2_block, "nAmax")
    if min(map(len, (s2_neurons, s2_pop, s2_gen, s2_rn, s2_an))) < 6:
        fail("Table S2 rows did not yield the BaZrO3 source column")
    # The paper uses the equal radial/angular basis order as nmax; derive it from both rows.
    if s2_rn[5] != s2_an[5]:
        fail("BaZrO3 radial and angular nmax values disagree in Table S2")
    s2_page = printed_page(s2_text, s2_i + 1)
    for cell, value, unit in [
        ("BaZrO3 Nneu", s2_neurons[5], "neurons"),
        ("BaZrO3 Ngen", s2_gen[5], "generations"),
        ("BaZrO3 Npop", s2_pop[5], "1"),
        ("BaZrO3 nmax", s2_rn[5], "dimensionless"),
    ]:
        add_value(values, "Table S2", cell, value, unit,
                  f"{ARTICLE_CITATION}, Supporting Information Table S2 (p. {s2_page})")

    s3_i, s3_text = page_containing(si, "Table S3:")
    s3_text = compact(s3_text)
    s3_block = s3_text[s3_text.find("Table S3:"):]
    s3_neurons = normalized_table_row(s3_block, "Nneu")
    s3_gen = normalized_table_row(s3_block, "Ngen")
    if not s3_neurons or not s3_gen:
        fail("Table S3 rows did not yield liquid-water values")
    s3_page = printed_page(s3_text, s3_i + 1)
    add_value(values, "Table S3", "liquid water Nneu", s3_neurons[0], "neurons",
              f"{ARTICLE_CITATION}, Supporting Information Table S3 (p. {s3_page})")
    add_value(values, "Table S3", "liquid water Ngen", s3_gen[0], "generations",
              f"{ARTICLE_CITATION}, Supporting Information Table S3 (p. {s3_page})")

    bzo_i, bzo_text = page_containing(article, "reference data set contained")
    bzo_compact = compact(bzo_text)
    bzo_match = re.search(r"reference data set contained (\d+) structures", bzo_compact)
    if not bzo_match:
        fail("Could not extract BaZrO3 structure count from the article")
    bzo_structures = float(bzo_match.group(1))
    # The quoted R2 means are stated in SI Section S6 following the five-fold validation description.
    s6_i, s6_text = page_containing(si, "Their mean coefficient of determination")
    s6_compact = compact(s6_text).replace("−", "-")
    r2_match = re.search(r"mean coefficient of determination \( R2\) was ([0-9.]+)\(\d+\) for the diagonal and ([0-9.]+)\(\d+\) for the off-diagonal", s6_compact, re.IGNORECASE)
    if not r2_match:
        fail("Could not extract BaZrO3 cross-validation R2 values from SI Section S6")
    add_value(values, "Text", "BaZrO3 structures", bzo_structures, "structures",
              f"{ARTICLE_CITATION}, Sec. 4.4 (PDF p. {bzo_i + 1})")
    add_value(values, "Text", "BaZrO3 R2 diagonal", float(r2_match.group(1)), "dimensionless",
              f"{ARTICLE_CITATION}, Supporting Information Sec. S6 (PDF p. {s6_i + 1})")
    add_value(values, "Text", "BaZrO3 R2 off-diagonal", float(r2_match.group(2)), "dimensionless",
              f"{ARTICLE_CITATION}, Supporting Information Sec. S6 (PDF p. {s6_i + 1})")

    oh_i, oh_text = page_containing(article, "full width at half-maximum of this band")
    oh_compact = compact(oh_text).replace("−", "-")
    oh_match = re.search(r"yields a value of ([0-9.]+) cm-1 for the full width at half-maximum", oh_compact)
    exp_match = re.search(r"experimental estimates of about ([0-9.]+) cm-1", oh_compact)
    if not oh_match or not exp_match:
        fail("Could not extract OH-stretch FWHM comparison from the article")
    add_value(values, "Text", "OH stretch FWHM cm-1", float(oh_match.group(1)), "cm^-1",
              f"{ARTICLE_CITATION}, Sec. 4.1 (PDF p. {oh_i + 1})")
    add_value(values, "Text", "experimental FWHM cm-1", float(exp_match.group(1)), "cm^-1",
              f"{ARTICLE_CITATION}, Sec. 4.1 (PDF p. {oh_i + 1})")

    t1_page_text = article[t1_page]
    t1_block = section(t1_page_text, "Table 1.", "Figure 2.")
    water_normalization = re.search(r"dipole moment is given per ([A-Za-z ]+)\.", t1_block, re.IGNORECASE)
    if not water_normalization or "water molecule" not in water_normalization.group(1).casefold():
        fail("Table 1 does not expose the required liquid-water dipole normalization footnote")
    qm_unit_source = re.search(r"1\.80\s*×\s*10−3\s*e·bohr\s+(atom)−1", compact(qm_text))
    if not qm_unit_source:
        fail("The QM7B source does not state a per-atom dipole unit")
    unit_page_i, unit_text = page_containing(article, "Here, we use e·bohr for")
    unit_match = re.search(r"Here, we use ([^ ]+) for μ and ([^ ]+) for α, whereas χ is ([^.]+)\.", compact(unit_text))
    if not unit_match:
        fail("Could not parse the article's dipole, polarizability, and susceptibility unit convention")
    mu_unit_source, alpha_unit_source, chi_unit_source = unit_match.groups()
    if (mu_unit_source, alpha_unit_source, chi_unit_source.casefold()) != ("e·bohr", "bohr3", "unitless"):
        fail("The article's reported tensor-property units do not match the supported source notation")
    s8_i, s8_text = page_containing(si, "For non-polar liquids or gases")
    s8_text = compact(s8_text)
    s8_sentence = compact(s8_text[s8_text.find("For non-polar liquids or gases"):])
    required_s8_evidence = ("non-polar liquids or gases", "mean-field approximation", "χe", "ρα", "3ϵ0", "isotropic", "scalars")
    if not all(term.casefold() in s8_sentence.casefold() for term in required_s8_evidence):
        fail("Supporting Information S8 is missing a required Clausius-Mossotti condition or equation term")
    # PDF text extraction linearizes the displayed fraction; the symbol sequence
    # and surrounding source definitions establish its numerator/denominator layout.
    eq_source = compact(s8_text[s8_text.find("is given by"):s8_text.find("where ρ is")])
    equation_match = re.search(r"χe\s+χe\s*\+\s*(\d+)\s*=\s*ρα\s+(\d+)ϵ0", eq_source)
    if not equation_match:
        fail("Could not identify the Clausius-Mossotti fraction in Supporting Information S8")
    cm_offset, cm_factor = map(int, equation_match.groups())
    cm_equation = f"chi/(chi + {cm_offset}) = rho*alpha/({cm_factor}*epsilon0)"
    # Hold chi/rho fixed (=1) and vary chi. The equation then yields two
    # distinct alpha values, proving that the ratio alone is insufficient.
    alpha_a = cm_factor / (1 + cm_offset)
    alpha_b = cm_factor / (2 + cm_offset)
    chi_rho_unique = math.isclose(alpha_a, alpha_b, rel_tol=1e-12)
    if chi_rho_unique:
        fail("Parsed Clausius-Mossotti relation did not distinguish the equal-ratio examples")
    table2_text = article[t2_page]
    if not re.search(r"χ/ρ.*?unit of polarizability per atom", compact(table2_text), re.IGNORECASE):
        fail("The article does not establish the liquid-water chi/rho per-entity convention")
    condition_match = re.search(r"For (non-polar liquids or gases).*?mean-field approximation.*?local field effect", s8_sentence, re.IGNORECASE)
    isotropic_match = re.search(r"all quantities here are isotropic and therefore represented by scalars", s8_sentence, re.IGNORECASE)
    if not condition_match or not isotropic_match:
        fail("Could not extract the source's Clausius-Mossotti applicability conditions")

    conventions = [
        {"topic": "liquid water dipole normalization",
         "statement": f"The Table 1 footnote states that the liquid-water dipole moment is given per {water_normalization.group(1).strip()}.",
         "basis": f"{ARTICLE_CITATION}, Table 1 footnote (PDF p. {t1_page + 1})"},
        {"topic": "qm7b normalization",
         "statement": f"The QM7B dipole RMSE unit is printed with denominator {qm_unit_source.group(1)}; the paired alpha RMSEs are reported per {qm_unit_source.group(1)} in the same validation-set passage.",
         "basis": f"{ARTICLE_CITATION}, Secs. 3.1–3.2 (PDF p. {qm_page + 1})"},
        {"topic": "unit conventions",
         "statement": f"The article states that μ uses {mu_unit_source}, α uses {alpha_unit_source}, and χ is {chi_unit_source}; SI Section S7 separately describes SI definitions and the role of molar density.",
         "basis": f"{ARTICLE_CITATION}, Sec. 2.5 (PDF p. {unit_page_i + 1}) and Supporting Information Sec. S7 (PDF p. {s8_i + 1})"},
        {"topic": "clausius-mossotti",
         "statement": f"The SI describes the relation for {condition_match.group(1)}, states that it is based on a mean-field approximation to account for local field effects, and specifies that {isotropic_match.group(0)}; the relation is explicitly approximate.",
         "basis": f"{ARTICLE_CITATION}, Supporting Information Sec. S8 (PDF p. {s8_i + 1})"},
        {"topic": "chi/rho reconstructability",
         "statement": f"Table 2 reports liquid-water χ/ρ as a ratio per water molecule. At fixed χ/ρ=1, the parsed Clausius-Mossotti relation gives alpha/epsilon0={alpha_a:g} for chi=1 and {alpha_b:g} for chi=2; therefore the ratio alone does not determine alpha.",
         "basis": f"{ARTICLE_CITATION}, Sec. 3.2 (PDF p. {t2_page + 1}) and Supporting Information Sec. S8 (PDF p. {s8_i + 1})"},
    ]
    benchmark_i, benchmark_text = page_containing(article, "Starting from a cell containing")
    benchmark_compact = compact(benchmark_text)
    range_match = re.search(r"Starting from a cell containing (\d+) atoms.*?up to (\d+) atoms", benchmark_compact)
    cpu_match = re.search(r"two Intel XEON Platinum [^,]+ processors", benchmark_compact)
    gpu_match = re.search(r"two Intel XEON Gold [^,]+ processors and an Nvidia GeForce RTX [^ ]+ card", benchmark_compact)
    if not range_match or not cpu_match or not gpu_match:
        fail("Could not extract the measured hardware or size range from Section 3.3")
    min_atoms, max_atoms = range_match.groups()
    hardware_summary = f"CPU server: {cpu_match.group(0)}; GPU server: {gpu_match.group(0)}; tested sizes: {min_atoms}–{max_atoms} atoms"
    aggregate_count = sum(1 for row in values if row["table"] in {"Table 1", "Table 2", "QM7B"})
    residual_a = [1.0, -1.0, 1.0, -1.0]
    residual_b = [math.sqrt(2), -math.sqrt(2), 0.0, 0.0]
    rms_a = math.sqrt(sum(x * x for x in residual_a) / len(residual_a))
    rms_b = math.sqrt(sum(x * x for x in residual_b) / len(residual_b))
    same_aggregate_different_tails = math.isclose(rms_a, rms_b) and max(map(abs, residual_a)) != max(map(abs, residual_b))
    if not same_aggregate_different_tails:
        fail("Could not construct equal-RMSE examples with different error tails")
    measured_scope_is_bounded = (0 < int(min_atoms) <= int(max_atoms)
                                 and bool(cpu_match.group(0)) and bool(gpu_match.group(0)))
    unsupported = [
        {"category": "hardware_performance_extrapolation", "supported": not measured_scope_is_bounded,
         "claim": "The measured speed advantage generalizes to untested hardware and system sizes beyond those studied.",
         "why": f"Section 3.3 reports measurements only on {hardware_summary}. Those observations bound the evidence to the named platforms and measured size interval, so performance on untested hardware or outside that interval is not established."},
        {"category": "per_configuration_error_distribution", "supported": not same_aggregate_different_tails,
         "claim": "The reported aggregate RMSE and R2 metrics determine the distribution of errors across individual configurations.",
         "why": f"The article reports {aggregate_count} aggregate validation cells across Tables 1–2 and QM7B, not per-configuration residual vectors. As a counterexample, residual arrays with equal RMSE {rms_a:g} can have maximum absolute errors {max(map(abs, residual_a)):g} and {max(map(abs, residual_b)):g}; aggregate metrics therefore do not fix the error tails."},
    ]
    output = {
        "source_version": ARTICLE_CITATION,
        "values": values,
        "normalized": {
            "liquid water dipole normalization": {"entity": water_normalization.group(1).strip()},
            "qm7b normalization": {"denominator_entity": qm_unit_source.group(1)},
            "unit conventions": {"mu": mu_unit_source.replace("·", "*"), "alpha": "bohr^3" if alpha_unit_source == "bohr3" else alpha_unit_source, "chi": chi_unit_source},
            "clausius-mossotti": {
                "equation": cm_equation,
                "applicability": [condition_match.group(1), isotropic_match.group(0), "mean-field approximation for local field effects"],
            },
            "chi/rho reconstructability": {
                "unique": chi_rho_unique,
                "reason": f"Two pairs with the same chi/rho=1 produce alpha/epsilon0={alpha_a:g} and {alpha_b:g} under the source equation, so the ratio alone does not uniquely determine alpha.",
            },
        },
        "conventions": conventions,
        "unsupported": unsupported,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "reconciliation.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
