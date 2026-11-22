"""Localize saved proof text from solver events and structured step evidence."""

import re

from . import predicate
from .state import bits, cell_name


TITLES = {
    "naked_single": "Naked single", "hidden_single": "Hidden single",
    "locked": "Locked candidates", "subset": "Naked subset", "hidden_subset": "Hidden subset",
    "x_wing": "X-Wing", "xy_wing": "XY-Wing", "w_wing": "W-Wing",
    "coloring": "Simple colouring", "medusa": "3D Medusa", "x_chain": "X-Chain", "als": "ALS-XZ",
    "forcing_chain": "Propagation refutation", "contradiction": "Refutation",
    "custom": "Custom constraint", "sum_link": "Shared sum", "ir_support": "Constraint support",
    "pattern_support": "Digit occupancy", "rule_choice": "Rule assignment", "full_rank": "Full Rank",
    "parity": "Parity", "odd": "Odd digits", "even": "Even digits", "clone": "Clone",
    "sandwich": "Sandwich sum", "skyscraper": "Skyscraper", "region_sum": "Region sum",
    "cage": "Killer cage", "thermo": "Thermometer", "arrow": "Arrow", "kropki": "Kropki dot",
    "xv": "XV sum", "x_sums": "X-Sum", "quadruple": "Quadruple",
    "exact_digits": "Fixed digit set", "palindrome": "Palindrome", "renban": "Renban",
    "german_whisper": "German Whisper", "dutch_whisper": "Dutch Whisper", "between": "Between line",
    "consecutive": "Consecutive line", "little_killer": "Little Killer", "product": "Product",
    "non_consecutive": "Nonconsecutive", "anti_knight": "Anti-knight", "anti_king": "Anti-king",
    "unit_peer": "Peer elimination", "chaos_pattern": "Region clue", "chaos_region": "Region deduction",
    "class_cover": "Digit classes", "innie": "Unit total", "outie": "Unit total",
    "constraint_simplify": "Constraint simplification", "candidate_map": "Candidate marks",
    "colour_class": "Colour classes", "intersection": "Overlapping constraints",
}


def _lists(values):
    return ", ".join(map(str, values))


def _unit(label):
    for pattern, replacement in (
        (r"第(\d+)行", r"row \1"), (r"第(\d+)列", r"column \1"), (r"区域(\d+)", r"region \1"),
        (r"第(\d+)条线", r"line \1"), (r"互异单元(\d+)", r"all-different unit \1"),
        (r"主对角线", "main diagonal"), (r"副对角线", "anti-diagonal"),
    ):
        if re.fullmatch(pattern, label or ""):
            return re.sub(pattern, replacement, label)
    return label if label and not re.search(r"[\u3400-\u9fff]", label) else "the marked unit"


def _label(label):
    match = re.fullmatch(r"(\d+)（(R\d+C\d+) ([左右上下])侧）", label)
    if match:
        value, cell, side = match.groups()
        return f"{value} ({cell}, {dict(zip('左右上下', ['left', 'right', 'top', 'bottom']))[side]})"
    return label if not re.search(r"[\u3400-\u9fff]", label) else None


def _cause(text, conflict, n):
    match = re.fullmatch(r"尾部和为 (\d+)，末格是 (\d+)，所以 (R\d+C\d+) 必须是 1，但该格已排除 1", text)
    if match:
        total, end, cell = match.groups()
        return f"The tail totals {total} and ends in {end}, so {cell} must be 1, which has already been excluded."
    if text and not re.search(r"[\u3400-\u9fff]", text):
        return text.rstrip(".") + "."
    if conflict and conflict.get("cells"):
        return "The assumption leaves no support at " + _lists(cell_name(c, n) for c in conflict["cells"]) + "."
    return "The remaining candidates cannot satisfy the selected rules."


def _assignment(data, name, n):
    regions = data["regions"]
    labels = [_label(region["label"]) or f"region {i + 1}" for i, region in enumerate(regions)]

    def selected(rules):
        return "; ".join(f"{label} uses {_label(rule) or 'the indicated rule'}"
                         for label, rule in zip(labels, rules))

    lines = []
    if data["quotas"] is not None:
        quotas = _lists(f"{_label(rule) or 'rule'} exactly {count} time(s)"
                        for rule, count in data["quotas"].items())
        lines.append(f"Each region uses one rule, with {quotas}.")
    for label, region in zip(labels, regions):
        for rule, cause in region["rejected"].items():
            lines.append(f"{label} cannot use {_label(rule) or 'that rule'}. {_cause(cause, None, n)}")
        for rule, witness in region["witnesses"].items():
            group = _lists(labels[i] for i in witness["regions"])
            lines.append(f"If {label} uses {_label(rule) or 'that rule'}, {group} have only "
                         f"{witness['slots']} available rule slots for {len(witness['regions'])} regions.")
        if len(region["remaining"]) == 1:
            lines.append(f"{label} must use {_label(region['remaining'][0]) or 'the remaining rule'}.")
    for failure in data.get("failures", [])[:4]:
        lines.append(f"Consider the assignment where {selected(failure['rules'])}. "
                     + _cause(failure["reason"], None, n))
    for branch in data.get("assignments", [])[:4]:
        if not branch["facts"]:
            continue
        lines.append(f"Consider the assignment where {selected(branch['rules'])}.")
        for premise in branch["premises"]:
            if premise["kind"] == "rank_head":
                lines.append(f"Rank {premise['rank']} starts with {premise['head']}.")
            elif len(premise["lengths"]) == 1:
                length = premise["lengths"][0]
                lines.append(f"The first {length} cells sum to {premise['sum']}, "
                             f"leaving {premise['complement']} for the rest of the unit.")
        lines.append("This gives " + _lists(f"{name(cell)} = {value}"
                                           for cell, value in branch["facts"][:4]) + ".")
    for lock in data.get("occupancy", []):
        hosts = _lists(name(c) for c in lock["hosts"])
        lines.append(f"Every surviving assignment places {lock['digit']} in {hosts} "
                     f"within {_unit(lock['unit'])}. Remove it from the rest of that unit.")
    lines.append("Keep candidates supported by at least one surviving assignment.")
    return "\n".join(lines)


def _event_text(event, name):
    symbol = "=" if event["kind"] == "place" else "≠"
    return f"{name(event['cell'])} {symbol} {event['value']}"


def _refutation(payload, evidence, primary, name, n):
    phase = evidence.get("phase") or primary.get("phase")
    cell, value = evidence.get("cell", primary.get("cell")), evidence.get("value", primary.get("value"))
    assumption = f"Assume {name(cell)} = {value}." if cell is not None else "Follow the marked assumption."
    if payload["revert"] or phase == "end":
        forced = primary.get("forced")
        result = f"Place {forced} in {name(cell)}." if forced else f"Eliminate {value} from {name(cell)}."
        return "Restore board", f"Undo the assumption {name(cell)} = {value}. {result}", assumption
    if phase == "trace":
        lines = [assumption]
        for row in evidence["rows"]:
            kind = row["kind"]
            if kind == "event":
                event = row["event"]
                label = TITLES.get(event["reason"]["kind"], "constraint propagation")
                reason = event["reason"]["data"]
                if "proof_partner" in reason:
                    partner = name(reason["proof_partner"])
                    digits = _lists(reason.get("proof_values", []))
                    why = (f"the only compatible candidates at {partner} ({digits}) have been eliminated"
                           if digits else f"{partner} has no compatible candidate")
                    label = f"{label}: {why}"
                elif event["reason"]["kind"] == "unit_peer":
                    label = f"it sees {name(reason['by'])} in the same unit"
                lines.append(f"{_event_text(event, name)} ({label}).")
            elif kind == "cause":
                lines.append(_cause(row["text"], row.get("conflict"), n))
            elif kind == "assume":
                lines.append(f"Now assume {name(row['cell'])} = {row['value']}.")
            elif kind == "branch":
                lines.append(f"Check the remaining candidates {_lists(row['values'])} at {name(row['cell'])}.")
            else:
                lines.append("Every candidate in this branch leads to a contradiction.")
        return f"Refutation evidence {evidence['page']}/{evidence['total']}", "\n".join(lines), assumption
    if phase == "conflict":
        note = _cause(evidence["cause"], evidence.get("conflict"), n)
        return "Contradiction", f"{assumption} {note} The assumption fails.", assumption
    return "Test an assumption", assumption, assumption


def english_step(payload, n, evidence):
    def name(cell):
        return cell_name(cell, n)

    technique = payload["technique"]
    events = payload["events"]
    event = next((e for e in events if e["reason"]["kind"] != "unit_peer"), None)
    reason = event["reason"] if event else {"kind": technique, "data": {}}
    d = reason["data"]
    title = TITLES.get(technique, "Deduction")
    assumption = None
    if technique == "contradiction":
        title, detail, assumption = _refutation(payload, evidence, d, name, n)
    else:
        try:
            detail = _explain(payload, reason["kind"], d, evidence, name, n)
        except (KeyError, ValueError, TypeError, IndexError):
            detail = f"Apply {title.lower()} to the marked cells and keep the supported candidates."
    visual = dict(payload["visual"])
    if visual.get("assumption"):
        visual["assumption"] = {**visual["assumption"], "label": assumption or "Assumption"}
    if visual.get("groups"):
        visual["groups"] = [
            {**group, "label": re.sub(r"^圈(\d+)$", r"Circle \1", group["label"])}
            if "label" in group else group for group in visual["groups"]
        ]
    if visual.get("chips"):
        visual["chips"] = [
            {**chip, "text": chip["text"].replace("和=", "Sum=").replace("见", "Visible: ")}
            if isinstance(chip.get("text"), str) else chip for chip in visual["chips"]
        ]
    payload["visual"] = visual
    payload.update(title=title, detail=detail)
    return payload


def _explain(payload, kind, d, evidence, name, n):
    technique = payload["technique"]
    visual = payload["visual"]
    def names(cells):
        return _lists(name(c) for c in cells)

    if technique == "candidate_map":
        return "Mark the remaining candidates listed for the highlighted cells."
    if technique == "chaos_pattern" and evidence:
        return (f"The clue at {names(evidence['cells'])} allows these region counts: "
                f"{_lists(evidence['counts'])}. Each region is connected and contains {n} distinct digits.")
    if technique in ("chaos_pattern", "chaos_region"):
        return (f"Use connected regions of {n} cells with distinct digits. "
                f"The marked cells ({names(visual.get('focus', []))}) show the region relationship under consideration.")
    if technique == "constraint_simplify":
        if "excluded_count" in evidence:
            return (f"At {names(evidence['cells'])}, assuming {evidence['excluded_count']} regions "
                    f"leads to a contradiction. The remaining counts are {_lists(evidence['remaining'])}.")
        return f"The marked constraint can be rewritten using the current candidates at {names(visual.get('focus', []))}."
    if technique == "colour_class":
        return "The two marked V pairs account for digits 1–4. The affected cell sees all four classes by knight moves."
    if kind == "naked_single":
        return f"{name(d['cell'])} has only one remaining candidate, {d['value']}."
    if kind == "hidden_single":
        return f"In {_unit(d.get('unit'))}, only {name(d['cell'])} can contain {d['value']}."
    if kind == "locked":
        reasons = {(e["value"], e["reason"]["data"].get("target_unit")): e["reason"]["data"]
                   for e in payload["events"] if e["reason"]["kind"] == "locked"}
        return "\n".join(
            f"In {_unit(info['unit'])}, {value} can only appear in {names(info['cells'])}. "
            f"These cells all belong to {_unit(target)}, so the rest of that unit outside the source excludes {value}."
            for (value, target), info in reasons.items()
        )
    if kind in ("subset", "hidden_subset"):
        cells, digits, unit = names(d["cells"]), _lists(d["digits"]), _unit(d["unit"])
        if kind == "hidden_subset":
            return f"In {unit}, digits {digits} can only appear in {cells}. The cells must therefore contain those digits."
        return f"In {unit}, {cells} are restricted to {{{digits}}}. Other cells in that unit cannot use these digits."
    if kind == "rule_choice":
        return _assignment(d, name, n)
    if kind == "pattern_support":
        unit = _unit(d.get("unit"))
        if "digits" in d:
            return (f"Every feasible combination occupies digits {_lists(bits(d['digits']))} in {names(d['hosts'])}. "
                    f"The other cells in {unit} cannot use those digits.")
        lines = [f"Compare the feasible combinations in {names(d['scopes'][0])} and {names(d['scopes'][1])}."]
        if d["shared"]:
            lines.append(f"Both combinations must agree at {names(d['shared'])}.")
        if d["unit"]:
            lines.append(f"The two groups in {unit} cannot use the same digits.")
        lines.append("The eliminated candidates only appear in combinations without a compatible partner.")
        return " ".join(lines)
    if kind == "cage":
        combos = d.get("combos") or []
        lines = [f"The killer cage at {names(d['cells'])} totals {d['sum']}."]
        if combos:
            lines.extend([f"{len(combos)} viable combinations:",
                          *("{" + _lists(combo) + "}" for combo in combos[:8])])
        return "\n".join(lines)
    if kind in ("arrow", "xv", "x_sums", "full_rank", "sum_link", "innie", "outie"):
        if kind == "arrow":
            return f"The digit at {name(d['circle'])} equals the sum of the arrow at {names(d['arm'])}."
        if kind == "xv":
            return f"{name(d['a'])} and {name(d['b'])} add to {d['sum']}."
        if kind == "x_sums":
            text = f"The first digit gives the number of cells that must sum to {d['sum']}."
            if "complement" in d:
                text += f" The rest of the complete unit must sum to {d['complement']}."
            return text
        if kind == "full_rank":
            return (f"Each digit starts exactly four readings, so rank {d['rank']} must start with {d['head']}. "
                    "Only readings with that first digit affect its order within the group.")
        if kind == "sum_link":
            return (f"Both sums include {names(d['shared'])}. Cancelling those terms leaves {d['equation']}. "
                    "Keep only candidates with partners that satisfy this equation.")
        if kind in ("innie", "outie"):
            return f"The digits of {_unit(d['unit'])} add to {n * (n + 1) // 2}. Use the cages to find the sum left for the marked cells."
    if kind == "custom":
        scope = [name(c) for c in d["scope"]]
        equation = predicate.format_node(predicate.parse(d["predicate"]), scope)
        return f"The constraint on {_lists(scope)} is {equation}. Candidates must occur in a combination that satisfies it."
    if kind == "forcing_chain":
        trace = " → ".join(_event_text(e, name) for e in d.get("trace", []))
        return (f"Assume {name(d['cell'])} = {d['value']}.\n"
                + (trace + "\n" if trace else "")
                + f"Propagation leads to a contradiction, so remove {d['value']} from {name(d['cell'])}.")
    if kind == "class_cover":
        groups = _lists("{" + _lists(values) + "}" for values in d["classes"])
        loc = names(d["cells"])
        info = f"The 2×2 group at {loc} must contain a digit from each class: {groups}."
        if d.get("forced_cell") is not None and d.get("forced_class"):
            info += f" Only {name(d['forced_cell'])} can provide the class {{{_lists(d['forced_class'])}}}."
        return info
    if kind in ("quadruple", "exact_digits"):
        return f"The marked cells at {names(d['cells'])} must contain digits {_lists(d['digits'])}."
    if kind == "xy_wing":
        a, b, c = d["digits"]
        first, second = d["wings"]
        return (f"The pivot {name(d['pivot'])} has {{{a}, {b}}}. Its wings are {name(first)} "
                f"with {{{a}, {c}}} and {name(second)} with {{{b}, {c}}}. Either pivot value forces "
                f"{c} in one wing, so cells that see both wings exclude {c}.")
    if kind == "w_wing":
        digit, other = d["digits"]
        return (f"{names(d['cells'])} share candidates {{{digit}, {other}}}. The strong link at "
                f"{names(d['link'])} forces {other} into at least one wing. Cells seeing both exclude {other}.")
    if kind == "als":
        return (f"Compare the almost locked sets {names(d['als1'])} and {names(d['als2'])}. "
                f"Only one set can use their restricted common digit {d['x']}. Thus {d['z']} "
                "must occur in one set and is excluded wherever both sets' positions for it are seen.")
    if kind == "x_chain" and d["cells"]:
        return (f"Follow the alternating links for {d['digit']} through {names(d['cells'])}. "
                f"At least one endpoint must contain {d['digit']}, so {name(d['target'])} cannot.")
    if kind in ("coloring", "medusa"):
        if d.get("mode") == "wrap":
            return "Strong links alternate between two colours. One colour contains mutually conflicting candidates and is ruled out."
        if kind == "medusa" and d.get("mode") != "trap":
            return "One of the two colours is true. A cell containing both colours must use one of those two candidates."
        return "One colour must be true. Any candidate that sees both colours is ruled out."
    if kind == "skyscraper":
        return (f"Looking from the {d['direction']}, {d['clue']} buildings are visible in {names(d['cells'])}. "
                "A building is visible only if it is taller than all earlier ones.")
    statements = {
        "thermo": "Digits increase strictly from the bulb to the tip.",
        "renban": "The line contains distinct consecutive digits, in any order.",
        "palindrome": "Mirrored positions along the line must have the same digit.",
        "between": "Every interior digit lies strictly between the two end digits.",
        "clone": "Corresponding cells must have the same digit.",
        "german_whisper": f"Adjacent positions differ by at least {d.get('diff', 5)}.",
        "dutch_whisper": f"Adjacent positions differ by at least {d.get('diff', 4)}.",
        "consecutive": "Adjacent positions differ by exactly one.",
        "kropki": ("One digit is twice the other." if d.get("variant") == "black"
                   else "The two digits differ by exactly one."),
        "non_consecutive": "Adjacent cells cannot contain consecutive digits.",
        "anti_knight": "Cells a knight's move apart cannot contain the same digit.",
        "anti_king": "Touching cells, including diagonally, cannot contain the same digit.",
        "little_killer": f"The marked diagonal sums to {d.get('sum')}.",
        "sandwich": f"The digits between 1 and {n} sum to {d.get('sum')}.",
        "region_sum": "The segments formed by region boundaries all have the same sum.",
        "parity": f"This group can only use {d.get('kind', 'odd')} digits.",
        "x_wing": "The marked rows and columns share the same two positions for this digit, so it is excluded elsewhere on the crossing lines.",
        "x_chain": "Follow the marked single-digit links. Their endpoints rule out a shared candidate.",
    }
    scope = d.get("cells") or ([d["a"], d["b"]] if "a" in d and "b" in d else visual.get("focus", []))
    label = TITLES.get(kind, TITLES.get(technique, "Constraint"))
    where = f" at {names(scope)}" if scope else ""
    text = statements.get(kind)
    return (f"{label}{where}. {text}" if text else
            f"Apply {label.lower()}{where} and keep only candidates consistent with the marked constraints.")
