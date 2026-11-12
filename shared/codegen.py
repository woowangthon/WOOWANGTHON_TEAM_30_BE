#!/usr/bin/env python3
"""shared/schema.json → Pydantic 모델(server)과 TypeScript 타입(web)을 만든다.

TS 타입은 FE 저장소에 쓴다. 기본 위치는 같은 상위 폴더에 나란히 clone한 WOOWANGTHON_TEAM_30_FE이고,
환경 변수 WEB_DIR로 바꿀 수 있다. FE 저장소가 없으면 TS 타입은 건너뛴다.

사용법:
    python3 shared/codegen.py          # 파일 생성
    python3 shared/codegen.py --check  # 생성 결과가 커밋된 파일과 같은지 확인 (make lint)

외부 도구 없이 표준 라이브러리만 쓴다. 지원하는 JSON Schema 범위는 일부(object, array,
string/number/integer/boolean, enum, $ref, nullable, format date/date-time, 길이·개수 제약)다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "shared" / "schema.json"
PY_OUT = ROOT / "server" / "app" / "schemas" / "generated.py"
WEB_DIR = Path(os.environ.get("WEB_DIR") or ROOT.parent / "WOOWANGTHON_TEAM_30_FE")
if not WEB_DIR.is_absolute():
    WEB_DIR = (ROOT / WEB_DIR).resolve()
TS_OUT = WEB_DIR / "src" / "lib" / "api-types.gen.ts"

HEADER_NOTE = "자동 생성 파일입니다. 직접 고치지 말고 shared/schema.json을 고친 뒤 `make gen`을 실행하세요."


def ref_name(ref: str) -> str:
    assert ref.startswith("#/$defs/"), ref
    return ref[len("#/$defs/") :]


def split_nullable(schema: dict) -> tuple[dict, bool]:
    """nullable 표현(type 배열, anyOf null)을 떼어 (본 스키마, nullable 여부)를 돌려준다."""
    if "anyOf" in schema:
        options = schema["anyOf"]
        non_null = [o for o in options if o.get("type") != "null"]
        nullable = len(non_null) != len(options)
        if len(non_null) != 1:
            raise ValueError(f"anyOf는 [X, null] 형태만 지원합니다: {schema}")
        inner = dict(non_null[0])
        for k, v in schema.items():
            if k != "anyOf":
                inner.setdefault(k, v)
        return inner, nullable
    t = schema.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        nullable = len(non_null) != len(t)
        if len(non_null) != 1:
            raise ValueError(f"type 배열은 [X, 'null'] 형태만 지원합니다: {schema}")
        inner = dict(schema)
        inner["type"] = non_null[0]
        return inner, nullable
    return schema, False


def is_enum_def(schema: dict) -> bool:
    return schema.get("type") == "string" and "enum" in schema and "properties" not in schema


def upper_snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.upper())
    return "".join(out)


# ---------------------------------------------------------------- Python


def py_constraints(schema: dict) -> list[str]:
    mapping = {
        "minLength": "min_length",
        "maxLength": "max_length",
        "minItems": "min_length",
        "maxItems": "max_length",
        "minimum": "ge",
        "maximum": "le",
    }
    return [f"{mapping[k]}={schema[k]!r}" for k in mapping if k in schema]


def py_base_type(schema: dict) -> str:
    if "$ref" in schema:
        return ref_name(schema["$ref"])
    t = schema.get("type")
    if "enum" in schema:
        return "Literal[" + ", ".join(repr(v) for v in schema["enum"]) + "]"
    if t == "string":
        fmt = schema.get("format")
        if fmt == "date":
            return "dt.date"
        if fmt == "date-time":
            return "dt.datetime"
        return "str"
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    if t == "array":
        item_schema, item_nullable = split_nullable(schema["items"])
        item = py_base_type(item_schema)
        cons = py_constraints(item_schema)
        if cons and item_schema.get("type") == "string":
            item = f"Annotated[str, StringConstraints({', '.join(cons)})]"
        if item_nullable:
            item = f"Optional[{item}]"
        return f"list[{item}]"
    if t == "object":
        if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
            return f"dict[str, {py_base_type(schema['additionalProperties'])}]"
        return "dict[str, Any]"
    raise ValueError(f"지원하지 않는 스키마: {schema}")


def py_field(name: str, schema: dict, required: bool) -> str:
    inner, nullable = split_nullable(schema)
    typ = py_base_type(inner)
    has_default = "default" in schema or "default" in inner
    default = schema.get("default", inner.get("default"))
    if nullable or (not required and not has_default and inner.get("type") != "array"):
        typ = f"Optional[{typ}]"
    args: list[str] = []
    if not required:
        if has_default:
            args.append(f"default={default!r}")
        elif inner.get("type") == "array" and not nullable:
            args.append("default_factory=list")
        else:
            args.append("default=None")
    args += py_constraints(inner)
    desc = schema.get("description") or inner.get("description")
    if desc:
        args.append(f"description={desc!r}")
    if args:
        return f"    {name}: {typ} = Field({', '.join(args)})"
    return f"    {name}: {typ}"


def gen_python(defs: dict) -> str:
    lines = [
        f'"""{HEADER_NOTE}"""',
        "",
        "# ruff: noqa: E501",
        "from __future__ import annotations",
        "",
        "import datetime as dt",
        "from typing import Annotated, Any, Literal, Optional",
        "",
        "from pydantic import BaseModel, Field, StringConstraints",
        "",
        "__all__ = [",
    ]
    names = list(defs)
    for n in names:
        lines.append(f"    {n!r},")
        if is_enum_def(defs[n]):
            lines.append(f"    {upper_snake(n) + '_VALUES'!r},")
    lines += ["]", "", ""]

    for name, schema in defs.items():
        if is_enum_def(schema):
            values = schema["enum"]
            if schema.get("description"):
                lines.append(f"# {schema['description']}")
            lines.append(f"{name} = Literal[{', '.join(repr(v) for v in values)}]")
            lines.append(f"{upper_snake(name)}_VALUES: tuple[str, ...] = ({', '.join(repr(v) for v in values)},)")
            lines += ["", ""]

    for name, schema in defs.items():
        if is_enum_def(schema):
            continue
        if schema.get("type") != "object":
            raise ValueError(f"$defs.{name}: object 또는 string enum만 지원합니다")
        lines.append(f"class {name}(BaseModel):")
        if schema.get("description"):
            lines.append(f'    """{schema["description"]}"""')
            lines.append("")
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not props:
            lines.append("    pass")
        # 필수 필드 먼저 (가독성), 원래 순서 유지
        for prop, pschema in props.items():
            lines.append(py_field(prop, pschema, prop in required))
        lines += ["", ""]

    for name, schema in defs.items():
        if not is_enum_def(schema):
            lines.append(f"{name}.model_rebuild()")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- TypeScript


def ts_base_type(schema: dict) -> str:
    if "$ref" in schema:
        return ref_name(schema["$ref"])
    t = schema.get("type")
    if "enum" in schema:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "array":
        item_schema, item_nullable = split_nullable(schema["items"])
        item = ts_base_type(item_schema)
        if item_nullable:
            item = f"{item} | null"
        if "|" in item:
            item = f"({item})"
        return f"{item}[]"
    if t == "object":
        if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
            return f"Record<string, {ts_base_type(schema['additionalProperties'])}>"
        return "Record<string, unknown>"
    raise ValueError(f"지원하지 않는 스키마: {schema}")


def ts_doc(desc: str | None, indent: str = "") -> list[str]:
    if not desc:
        return []
    return [f"{indent}/** {desc} */"]


def gen_ts(defs: dict) -> str:
    lines = [f"// {HEADER_NOTE}", ""]
    for name, schema in defs.items():
        if is_enum_def(schema):
            const = upper_snake(name) + "_VALUES"
            lines += ts_doc(schema.get("description"))
            values = ", ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
            lines.append(f"export const {const} = [{values}] as const;")
            lines.append(f"export type {name} = (typeof {const})[number];")
            lines.append("")
    for name, schema in defs.items():
        if is_enum_def(schema):
            continue
        lines += ts_doc(schema.get("description"))
        lines.append(f"export interface {name} {{")
        required = set(schema.get("required", []))
        for prop, pschema in schema.get("properties", {}).items():
            inner, nullable = split_nullable(pschema)
            typ = ts_base_type(inner)
            if nullable:
                typ = f"{typ} | null"
            opt = "" if prop in required else "?"
            lines += ts_doc(pschema.get("description") or inner.get("description"), "  ")
            lines.append(f"  {prop}{opt}: {typ};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    defs = schema["$defs"]
    outputs = {PY_OUT: gen_python(defs)}
    if WEB_DIR.is_dir():
        outputs[TS_OUT] = gen_ts(defs)
    else:
        print(f"FE 저장소가 없어 TS 타입은 건너뜀: {WEB_DIR}", file=sys.stderr)
    check = "--check" in sys.argv
    stale = []
    for path, content in outputs.items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"생성: {path}")
    if stale:
        for p in stale:
            print(f"오래된 생성 파일: {p} — `make gen`을 실행하세요", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
