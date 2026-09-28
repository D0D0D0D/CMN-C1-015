"""PB — Sandbox escape resistance for DataAnalysisAgent.

The agent executes LLM-generated Python. These proof-of-boundary tests assert
that the static AST policy in src/services/code_sandbox.py blocks the known
escape vectors, and that legitimate analysis code still runs.
"""

import pytest

from src.services.code_sandbox import SandboxViolation, run_analysis, validate_code

DATA = [{"a": 1, "b": 10}, {"a": 2, "b": 20}, {"a": 3, "b": 30}]

# Each of these must be rejected by static analysis (SandboxViolation).
MALICIOUS = [
    pytest.param("import os\nresult = os.listdir('/')", id="import-os"),
    pytest.param("from subprocess import run\nresult = run(['ls'])", id="import-from"),
    pytest.param("result = __import__('os').system('id')", id="dunder-import-call"),
    pytest.param("result = open('/etc/passwd').read()", id="open"),
    pytest.param("result = eval('1+1')", id="eval-builtin"),
    pytest.param("result = exec('x=1')", id="exec-builtin"),
    pytest.param("result = ().__class__.__bases__[0].__subclasses__()", id="dunder-subclasses-escape"),
    pytest.param("result = getattr(df, 'to_csv')('/tmp/x')", id="getattr"),
    pytest.param("result = df.to_csv('/tmp/leak.csv')", id="pandas-to_csv"),
    pytest.param("import pandas as pd\nresult = pd.read_csv('/etc/passwd')", id="pandas-read_csv"),
    pytest.param("result = df.eval('a + b')", id="pandas-df-eval"),
    pytest.param("result = df.query('a > 1')", id="pandas-query"),
    pytest.param("result = globals()", id="globals"),
    pytest.param("result = type(df).__mro__", id="type-and-dunder"),
    pytest.param("class Evil:\n    pass\nresult = 1", id="classdef"),
    pytest.param("with open('x') as f:\n    result = 1", id="with"),
    # Module-submodule traversal escapes (review): exposing raw pandas/numpy
    # would reach these via plain attribute chains — denylisted + proxy-blocked.
    pytest.param("result = pd.io.common.get_handle('/etc/passwd', 'r')", id="pandas-io-get_handle"),
    pytest.param("result = np.ctypeslib.load_library('libc.so.6', '/lib')", id="numpy-ctypeslib"),
    pytest.param("result = np.lib.format.open_memmap('/tmp/x')", id="numpy-lib-open_memmap"),
]


class TestSandboxBlocksEscapes:
    @pytest.mark.parametrize("code", MALICIOUS)
    def test_static_validation_rejects(self, code):
        """validate_code() must raise on every known escape vector."""
        with pytest.raises(SandboxViolation):
            validate_code(code)

    @pytest.mark.parametrize("code", MALICIOUS)
    def test_run_analysis_rejects(self, code):
        """run_analysis() must never execute a policy-violating snippet."""
        with pytest.raises(SandboxViolation):
            run_analysis(code, DATA)

    def test_dunder_attribute_in_chain_blocked(self):
        with pytest.raises(SandboxViolation):
            validate_code("result = df.values.__class__")

    def test_pd_proxy_has_no_submodules(self):
        # Even if a denylisted name were missed, the proxy carries only
        # whitelisted callables — submodule traversal fails at runtime.
        from src.services.code_sandbox import _PANDAS_ALLOW, _NUMPY_ALLOW

        assert "io" not in _PANDAS_ALLOW and "core" not in _PANDAS_ALLOW
        assert "ctypeslib" not in _NUMPY_ALLOW and "lib" not in _NUMPY_ALLOW
        assert "DataFrame" in _PANDAS_ALLOW and "array" in _NUMPY_ALLOW


class TestSandboxAllowsLegitimateAnalysis:
    def test_simple_aggregation_runs(self):
        out = run_analysis("result = int(df['b'].sum())", DATA)
        assert out == "60"

    def test_groupby_runs(self):
        out = run_analysis("result = df['a'].max()", DATA)
        assert out == "3"

    def test_numpy_available(self):
        out = run_analysis("result = int(np.array(df['a']).sum())", DATA)
        assert out == "6"

    def test_missing_result_variable_raises_value_error(self):
        # Not a SandboxViolation — a runtime contract error that drives RETRY.
        with pytest.raises(ValueError):
            run_analysis("x = df['a'].sum()", DATA)
