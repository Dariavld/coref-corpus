import argparse
from typing import *

from merge import Entity, Markup, Span, read_markup


def diff(a: Markup, b: Markup, context_len: int = 32):
    if a.text != b.text:
        raise ValueError("Texts are not the same")
    a_spans = set(a.span2entity.keys())
    b_spans = set(b.span2entity.keys())

    a_not_b_spans = a_spans - b_spans
    if a_not_b_spans:
        print_separator("Spans in A but not in B")
        diff_spans(a, a_not_b_spans, context_len)

    b_not_a_spans = b_spans - a_spans
    if b_not_a_spans:
        print_separator("Spans in B but not in A")
        diff_spans(b, b_not_a_spans, context_len)

    common_spans = a_spans & b_spans
    entity_mapping = get_entity_mapping(a, b, common_spans)
    mixed_spans = set()
    for a_entity, b_entity in entity_mapping.items():
        mixed_spans.update((a_entity.spans & common_spans) - b_entity.spans)
    if mixed_spans:
        print_separator("Spans belonging to different entities")
        diff_entities(a, b, mixed_spans, a.text, context_len)

    missing_children_a = get_missing_children(
        a, b, common_spans, entity_mapping
    )
    if missing_children_a:
        print_separator("Children in A but not in B")
        diff_children(missing_children_a, a.text)

    missing_children_b = get_missing_children(
        b, a, common_spans, get_entity_mapping(b, a, common_spans)
    )
    if missing_children_b:
        print_separator("Children in B but not in A")
        diff_children(missing_children_b, a.text)


def diff_children(children_and_parents: Set[Tuple[Entity, Entity]],
                  text: str):
    for child, parent in sorted(children_and_parents,
                                key=lambda x: min(x[1].spans)):
        print(f"Parent: {entity_to_str(parent, text)}")
        print(f"Child:  {entity_to_str(child, text)}")
        print()


def diff_entities(a: Markup, b: Markup,
                  mixed_spans: Set[Span],
                  text: str,
                  context_len: int):
    for span in sorted(mixed_spans):
        a_entity = a.span2entity[span]
        b_entity = b.span2entity[span]

        print(f"Position:    {span}")
        print(f"Text:        {text[slice(*span)]}")
        print(f"Context:     {get_context(span, text, context_len)}")
        print(f"Entity in A: {entity_to_str(a_entity, text)}")
        print(f"Entity in B: {entity_to_str(b_entity, text)}")
        print()


def diff_spans(ref: Markup, spans: Set[Span], context_len: int):
    for span in sorted(spans):
        print(f"Entity:   {entity_to_str(ref.span2entity[span], ref.text)}")
        print(f"Position: {span}")
        print(f"Text:     {ref.text[slice(*span)]}")
        print(f"Context:  {get_context(span, ref.text, context_len)}")
        print()


def entity_to_str(entity: Entity, text, max_spans: int = 3) -> str:
    spans_by_length = sorted(entity.spans,
                             key=lambda x: x[1] - x[0], reverse=True)
    spans_by_position = sorted(spans_by_length[:max_spans])
    label = f"<<{'//'.join('{}' for _ in spans_by_position)}>>"
    return label.format(*(text[slice(*span)]
                            for span in spans_by_position))


def get_context(span: Span, text: str, context_len: int) -> str:
    return repr(f"{text[span[0] - context_len:span[0]]}"
                f">>{text[slice(*span)]}<<"
                f"{text[span[1]:span[1] + context_len]}")


def get_entity_mapping(a: Markup,
                       b: Markup,
                       common_spans: Set[Span]) -> Dict[Entity, Entity]:
    mapping = {}
    for a_entity in a.entities:
        if any(span in common_spans for span in a_entity.spans):
            mapping[a_entity] = max(
                b.entities,
                key=lambda b_entity: len(a_entity.spans & b_entity.spans)
            )
    return mapping


def get_missing_children(a: Markup,
                         b: Markup,
                         common_spans: Set[Span],
                         entity_mapping: Dict[Entity, Entity]
                         ) -> Set[Tuple[Entity, Entity]]:
    missing_children = set()
    for a_entity, b_entity in entity_mapping.items():
        a_children = {entity_mapping[a.span2entity[span]]
                      for span in (a_entity.included_spans & common_spans)}
        b_children = {b.span2entity[span]
                      for span in (b_entity.included_spans & common_spans)}
        missing_children.update((child, a_entity)
                                for child in (a_children - b_children))
    return missing_children


def lea(a: Markup, b: Markup, eps: float = 1e-7) -> float:
    a_clusters = sorted(sorted(entity.spans) for entity in a.entities)
    b_clusters = sorted(sorted(entity.spans) for entity in b.entities)

    recall, r_weight = _lea(a_clusters, b_clusters)
    precision, p_weight = _lea(b_clusters, a_clusters)

    doc_precision = precision / (p_weight + eps)
    doc_recall = recall / (r_weight + eps)
    doc_f1 = (doc_precision * doc_recall) \
        / (doc_precision + doc_recall + eps) * 2
    return doc_f1


def _lea(key: List[List[Span]],
         response: List[List[Span]]) -> Tuple[float, float]:
        """ See aclweb.org/anthology/P16-1060.pdf. """
        response_clusters = [set(cluster) for cluster in response]
        response_map = {mention: cluster
                        for cluster in response_clusters
                        for mention in cluster}
        importances = []
        resolutions = []
        for entity in key:
            size = len(entity)
            if size == 1:  # entities of size 1 are not annotated
                continue
            importances.append(size)
            correct_links = 0
            for i in range(size):
                for j in range(i + 1, size):
                    correct_links += int(entity[i]
                                         in response_map.get(entity[j], {}))
            resolutions.append(correct_links / (size * (size - 1) / 2))
        res = sum(imp * res for imp, res in zip(importances, resolutions))
        weight = sum(importances)
        return res, weight


def print_separator(message: str, width: int = 120):
    line_width = max(0, width - len(message) - 1)
    print(f"\n{message} {'=' * line_width}\n")


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument("file", nargs=2,
                           help="Paths to markup files to compare")
    args = argparser.parse_args()

    versions = []
    for filename in args.file:
        versions.append(read_markup(filename))

    diff(*versions)

    print_separator("Metrics")
    print(f"LEA (without child spans): {lea(*versions):.3f}")