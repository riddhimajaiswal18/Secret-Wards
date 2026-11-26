"""Secure XML parsing into an ordered, lossless element-tree representation."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from io import StringIO
from typing import Any

from src.ir import IntermediateRepresentation, build_json_ir


def _xml_node(element: ET.Element, depth: int = 0, max_depth: int = 512) -> dict[str, Any]:
    if depth > max_depth:
        raise ValueError("xml_depth_limit_exceeded")
    if element.tag is ET.Comment:
        return {"node_type": "comment", "text": element.text, "tail": element.tail}
    if element.tag is ET.ProcessingInstruction:
        return {"node_type": "processing_instruction", "text": element.text, "tail": element.tail}
    return {
        "node_type": "element",
        "tag": element.tag,
        "attributes": [[key, value] for key, value in element.attrib.items()],
        "text": element.text,
        "children": [_xml_node(child, depth + 1, max_depth) for child in list(element)],
        "tail": element.tail,
    }


def parse_xml_ir(text: str, *, document_id: str, filename: str,
                 encoding: str, bom: bool = False) -> IntermediateRepresentation:
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("xml_dtd_or_entity_forbidden") from None
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        root = None
        namespaces: list[list[str]] = []
        for event, value in ET.iterparse(StringIO(text), events=("start", "start-ns"), parser=parser):
            if event == "start-ns":
                prefix, uri = value
                namespaces.append([prefix or "", uri])
            elif root is None:
                root = value
        if root is None:
            raise ET.ParseError("missing root element")
    except (ET.ParseError, RecursionError, ValueError):
        raise ValueError("malformed_xml") from None
    data = _xml_node(root)
    declaration = text.lstrip().split("?>", 1)[0] + "?>" if text.lstrip().startswith("<?xml") else None
    return build_json_ir(data, document_id=document_id, filename=filename, encoding=encoding,
                         source_format="xml", arrangement="ordered_xml_tree",
                         original_layout={"bom": bom, "xml_declaration": declaration,
                                          "namespaces": namespaces})
