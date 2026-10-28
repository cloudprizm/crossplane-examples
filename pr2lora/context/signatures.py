"""Sygnatury funkcji/klas przez tree-sitter (pełne, także wielolinijkowe).

pip install tree-sitter tree-sitter-language-pack
Gdy pakietów nie ma, repo_map.py automatycznie przechodzi na regex.
Uwaga: API py-tree-sitter zmieniało się między wersjami - sprawdź na swojej wersji.
"""
import pathlib

LANG = {".py": "python", ".go": "go", ".ts": "typescript"}
# typy węzłów z definicjami; ciało (pole "body") ucinamy, zostaje sama sygnatura
DEFS = {
    "python": {"function_definition", "class_definition"},
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "typescript": {"function_declaration", "class_declaration", "method_definition",
                   "interface_declaration"},
}


def available():
    try:
        import tree_sitter_language_pack  # noqa: F401
        return True
    except ImportError:
        return False


def signatures(path):
    from tree_sitter_language_pack import get_parser

    path = pathlib.Path(path)
    lang = LANG.get(path.suffix)
    if not lang:
        return []
    src = path.read_bytes()
    tree = get_parser(lang).parse(src)
    out = []

    def walk(node, depth=0):
        if node.type in DEFS[lang]:
            body = node.child_by_field_name("body")
            end = body.start_byte if body else node.end_byte
            sig = " ".join(src[node.start_byte:end].decode(errors="ignore").split())
            out.append("  " * (depth + 1) + sig.rstrip(":{ "))
            depth += 1  # metody w klasie z wcięciem
        for child in node.children:
            walk(child, depth)

    walk(tree.root_node)
    return out
