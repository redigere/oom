#!/usr/bin/env python3
import glob
import os
import sys
import yaml

HANDOFF = os.path.dirname(os.path.abspath(__file__))
SCHEMAS = os.path.join(HANDOFF, "_schemas")

failures = 0


def fail(msg):
    global failures
    failures += 1
    sys.stderr.write(msg + "\n")


TYPE_CHECKERS = {
    str: lambda v: isinstance(v, str),
    bool: lambda v: isinstance(v, bool),
    int: lambda v: isinstance(v, int),
    list: lambda v: isinstance(v, list),
    dict: lambda v: isinstance(v, dict),
}

TYPE_NAMES = {
    str: "str",
    bool: "bool",
    int: "int",
    list: "list",
    dict: "dict",
}


def validate_schema(data, schema, path=""):
    required = schema.get("required", [])
    for key in required:
        if key not in data:
            fail(f"{path}{key}: missing required key")
    properties = schema.get("properties", {})
    for key, props in properties.items():
        if key not in data:
            continue
        val = data[key]
        expected = props.get("type")
        if expected:
            checker = TYPE_CHECKERS.get(expected)
            if checker and not checker(val):
                fail(f"{path}{key}: expected {TYPE_NAMES.get(expected, expected)}, got {type(val).__name__}")
        if expected == dict and isinstance(val, dict):
            nested = {k: v for k, v in props.items() if k in ("required", "properties")}
            if nested:
                validate_schema(val, nested, f"{path}{key}.")
        if expected == list and isinstance(val, list):
            item_schema = props.get("items")
            if item_schema:
                for idx, item in enumerate(val):
                    if isinstance(item, dict):
                        validate_schema(item, item_schema, f"{path}{key}[{idx}].")


handoff_files = sorted(glob.glob(os.path.join(HANDOFF, "*.yml")))

if not handoff_files:
    sys.stderr.write("no handoff files\n")
    sys.exit(1)

for fpath in handoff_files:
    basename = os.path.basename(fpath)
    schema_path = os.path.join(SCHEMAS, basename)
    with open(fpath) as f:
        raw = f.read()
    try:
        data = yaml.safe_load(raw)
    except Exception as e:
        fail(f"{basename}: invalid yaml - {e}")
        continue
    if data is None:
        fail(f"{basename}: empty")
        continue
    if os.path.isfile(schema_path):
        with open(schema_path) as sf:
            try:
                schema = yaml.safe_load(sf)
            except Exception as e:
                fail(f"{basename}: invalid schema - {e}")
                continue
        if schema:
            validate_schema(data, schema)
    sys.stdout.write(basename + "\n")
    sys.stdout.write(raw)

if failures:
    sys.exit(1)
