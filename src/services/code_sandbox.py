"""AgentCore Platform v1.0 — restricted code sandbox for DataAnalysisAgent.

Service layer: executes LLM-generated pandas/numpy code against a caller-supplied
dataset.  This is a *defence-in-depth* boundary, not a kernel-level jail:

  1. AST static analysis rejects dangerous constructs BEFORE execution
     (imports, dunder access, eval/exec/open/getattr, pandas/numpy I/O escapes).
  2. Execution runs in a namespace whose __builtins__ is a small safe subset,
     with only `df` / `pd` / `np` / `math` / `statistics` injected.

Known limitation (see docs/07_operation_guide.md): there is NO CPU / memory /
wall-clock isolation and no process/container boundary.  A determined attacker
with an infinite loop can still hang the worker.  Hard resource isolation is a
platform concern tracked separately; the AST + restricted-builtins layer is the
first line of defence and is what the proof-of-boundary tests verify.
"""

from __future__ import annotations

import ast
import math
import statistics
from types import SimpleNamespace
from typing import Any

# Builtin names that must never be called or referenced in generated code.
_FORBIDDEN_NAMES: frozenset[str] = frozenset({
    "eval", "exec", "compile", "open", "__import__", "input",
    "getattr", "setattr", "delattr", "hasattr",
    "globals", "locals", "vars", "dir",
    "type", "object", "super", "classmethod", "staticmethod", "property",
    "breakpoint", "memoryview", "help", "exit", "quit", "license", "copyright",
})

# Attribute names that reach the host or bypass AST inspection (pandas/numpy
# I/O escapes, string-eval helpers, OS shells).  Dunder access is rejected
# separately and unconditionally.
_FORBIDDEN_ATTRS: frozenset[str] = frozenset({
    # string-eval / dynamic execution
    "eval", "query", "exec", "compile",
    # pandas readers / writers (filesystem / network / pickle)
    "read_csv", "read_table", "read_fwf", "read_excel", "read_json", "read_html",
    "read_xml", "read_parquet", "read_feather", "read_orc", "read_hdf", "read_sql",
    "read_sql_query", "read_sql_table", "read_pickle", "read_stata", "read_sas",
    "read_spss", "read_clipboard", "read_gbq",
    "to_csv", "to_excel", "to_json", "to_parquet", "to_feather", "to_orc",
    "to_hdf", "to_sql", "to_pickle", "to_stata", "to_clipboard", "to_gbq",
    # numpy I/O
    "load", "loadtxt", "fromfile", "save", "savetxt", "savez", "savez_compressed",
    "tofile", "memmap", "genfromtxt", "open_memmap", "fromregex", "frombuffer",
    # submodules that re-expose imports / file handles / C libraries
    # (defence-in-depth: the primary control is the whitelist proxy below, but
    # rejecting these statically gives a clear error). e.g. pd.io.common.get_handle,
    # np.ctypeslib.load_library, np.lib.format.open_memmap.
    "io", "common", "ctypeslib", "lib", "core", "get_handle", "DataSource", "ctypes",
    # OS / subprocess / filesystem
    "system", "popen", "Popen", "call", "run", "check_output", "getoutput",
    "spawn", "fork", "execve", "execv", "remove", "unlink", "rmdir", "mkdir",
    "rename", "chmod", "write", "writelines", "fdopen",
})

# Whitelisted module attributes — only these names are exposed on the `pd` / `np`
# proxies in the sandbox. Exposing the raw modules is unsafe: their submodules
# (pd.io, np.ctypeslib, np.lib) re-expose imports / file handles / C libraries
# via plain (non-dunder) attribute chains, bypassing the AST denylist.
_PANDAS_ALLOW = frozenset({
    "DataFrame", "Series", "Index", "MultiIndex", "Categorical",
    "concat", "merge", "pivot_table", "crosstab", "cut", "qcut", "get_dummies",
    "to_numeric", "to_datetime", "to_timedelta", "date_range", "factorize",
    "isna", "notna", "isnull", "notnull", "unique",
    "Timestamp", "Timedelta", "NA", "NaT",
})
_NUMPY_ALLOW = frozenset({
    "array", "asarray", "arange", "linspace", "zeros", "ones", "full", "eye",
    "mean", "median", "average", "sum", "prod", "std", "var", "min", "max", "ptp",
    "percentile", "quantile", "sort", "argsort", "argmax", "argmin", "unique",
    "where", "clip", "abs", "absolute", "round", "floor", "ceil", "trunc",
    "sqrt", "exp", "log", "log2", "log10", "power", "sign", "dot",
    "cumsum", "cumprod", "diff", "isnan", "isfinite", "isinf",
    "corrcoef", "cov", "histogram", "bincount", "digitize",
    "concatenate", "stack", "vstack", "hstack", "maximum", "minimum",
    "nanmean", "nansum", "nanstd", "nanmax", "nanmin", "nanmedian",
    "nan", "inf", "pi", "e",
})


class SandboxViolation(Exception):
    """Raised when generated code violates the sandbox policy (static check)."""


class _Validator(ast.NodeVisitor):
    """Reject any construct that could escape the sandbox."""

    def _check_identifier(self, name: str | None, node: ast.AST) -> None:
        if name and "__" in name:
            raise SandboxViolation(
                f"dunder access is forbidden: '{name}' (line {getattr(node, 'lineno', '?')})"
            )

    def visit_Import(self, node: ast.Import) -> None:
        raise SandboxViolation("import statements are forbidden in generated code")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise SandboxViolation("import statements are forbidden in generated code")

    def visit_Name(self, node: ast.Name) -> None:
        self._check_identifier(node.id, node)
        if node.id in _FORBIDDEN_NAMES:
            raise SandboxViolation(f"forbidden builtin reference: '{node.id}'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._check_identifier(node.attr, node)
        if node.attr in _FORBIDDEN_ATTRS:
            raise SandboxViolation(f"forbidden attribute access: '.{node.attr}'")
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        self._check_identifier(node.arg, node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_identifier(node.name, node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        raise SandboxViolation("async constructs are forbidden in generated code")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        raise SandboxViolation("class definitions are forbidden in generated code")

    def visit_With(self, node: ast.With) -> None:
        raise SandboxViolation("with statements are forbidden in generated code")

    def visit_Global(self, node: ast.Global) -> None:
        raise SandboxViolation("global/nonlocal statements are forbidden")

    visit_Nonlocal = visit_Global


# Safe builtins exposed to generated code — pure, side-effect-free helpers only.
def _safe_builtins() -> dict[str, Any]:
    safe_names = [
        "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter",
        "float", "frozenset", "int", "len", "list", "map", "max", "min", "print",
        "range", "reversed", "round", "set", "slice", "sorted", "str", "sum",
        "tuple", "zip", "True", "False", "None",
    ]
    import builtins as _b

    out: dict[str, Any] = {}
    for n in safe_names:
        if hasattr(_b, n):
            out[n] = getattr(_b, n)
    return out


def validate_code(code: str) -> None:
    """Static-analyse `code`; raise SandboxViolation if it breaks policy."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise SandboxViolation(f"syntax error in generated code: {e}") from e
    _Validator().visit(tree)


def _safe_module(module: Any, allow: frozenset[str]) -> SimpleNamespace:
    """Return a proxy exposing only whitelisted attributes of `module`.

    Critical: never expose the raw pandas/numpy module. Their submodules
    (pd.io, np.ctypeslib, np.lib) re-expose imports, file handles and C
    libraries through plain attribute chains that the AST denylist cannot
    catch. The proxy simply does not carry those attributes, so any traversal
    to them fails with AttributeError at runtime.
    """
    return SimpleNamespace(**{n: getattr(module, n) for n in allow if hasattr(module, n)})


def run_analysis(code: str, dataset: list[dict], allowed_libs: list[str] | None = None) -> str:
    """Validate and execute `code` against `dataset`, returning str(result).

    The generated code must assign its final answer to a variable named
    `result`.  A pandas DataFrame `df` built from `dataset` plus curated `pd`,
    `np` proxies (whitelisted attributes only) and `math` / `statistics` are
    available.  Raises SandboxViolation on a static-policy breach; lets
    execution errors (NameError, KeyError, missing `result`, etc.) propagate to
    the caller so the node can drive a RETRY.
    """
    validate_code(code)

    # Imported lazily so the module imports even if pandas/numpy are absent
    # at static-analysis time (the validator above needs neither).
    import numpy as np
    import pandas as pd

    df = pd.DataFrame(dataset)

    allowed = {lib.strip().lower() for lib in (allowed_libs or [])}
    namespace: dict[str, Any] = {
        "__builtins__": _safe_builtins(),
        "df": df,
        "math": math,
        "statistics": statistics,
    }
    # pandas/numpy exposed as curated proxies (never the raw modules), gated by
    # config.allowed_libs so the surface can be narrowed further.
    if not allowed or "pandas" in allowed:
        namespace["pd"] = _safe_module(pd, _PANDAS_ALLOW)
    if not allowed or "numpy" in allowed:
        namespace["np"] = _safe_module(np, _NUMPY_ALLOW)

    exec(code, namespace)  # noqa: S102 — sandboxed: AST-validated + restricted builtins

    if "result" not in namespace:
        raise ValueError(
            "generated code did not assign a 'result' variable "
            "(the final answer must be stored in `result`)"
        )
    return str(namespace["result"])
