import numpy as np
import numpy.linalg
import pytest

import theano
from tests import unittest_tools as utt
from tests.test_rop import break_op
from theano import config, function, tensor

# The one in comment are not tested...
from theano.sandbox.linalg.ops import Cholesky  # PSD_hint,; op class
from theano.sandbox.linalg.ops import (
    Solve,
    imported_scipy,
    inv_as_solve,
    matrix_inverse,
    solve,
    spectral_radius_bound,
)
from theano.tensor import DimShuffle
from theano.tensor.basic import _allclose
from theano.tensor.nlinalg import MatrixInverse


def test_rop_lop():
    mx = tensor.matrix("mx")
    mv = tensor.matrix("mv")
    v = tensor.vector("v")
    y = matrix_inverse(mx).sum(axis=0)

    yv = tensor.Rop(y, mx, mv)
    rop_f = function([mx, mv], yv)

    sy, _ = theano.scan(
        lambda i, y, x, v: (tensor.grad(y[i], x) * v).sum(),
        sequences=tensor.arange(y.shape[0]),
        non_sequences=[y, mx, mv],
    )
    scan_f = function([mx, mv], sy)

    rng = np.random.RandomState(utt.fetch_seed())
    vx = np.asarray(rng.randn(4, 4), theano.config.floatX)
    vv = np.asarray(rng.randn(4, 4), theano.config.floatX)

    v1 = rop_f(vx, vv)
    v2 = scan_f(vx, vv)

    assert _allclose(v1, v2), f"ROP mismatch: {v1} {v2}"

    raised = False
    try:
        tensor.Rop(theano.clone(y, replace={mx: break_op(mx)}), mx, mv)
    except ValueError:
        raised = True
    if not raised:
        raise Exception(
            "Op did not raised an error even though the function"
            " is not differentiable"
        )

    vv = np.asarray(rng.uniform(size=(4,)), theano.config.floatX)
    yv = tensor.Lop(y, mx, v)
    lop_f = function([mx, v], yv)

    sy = tensor.grad((v * y).sum(), mx)
    scan_f = function([mx, v], sy)

    v1 = lop_f(vx, vv)
    v2 = scan_f(vx, vv)
    assert _allclose(v1, v2), f"LOP mismatch: {v1} {v2}"


def test_spectral_radius_bound():
    tol = 10 ** (-6)
    rng = np.random.RandomState(utt.fetch_seed())
    x = theano.tensor.matrix()
    radius_bound = spectral_radius_bound(x, 5)
    f = theano.function([x], radius_bound)

    shp = (3, 4)
    m = rng.rand(*shp)
    m = np.cov(m).astype(config.floatX)
    radius_bound_theano = f(m)

    # test the approximation
    mm = m
    for i in range(5):
        mm = np.dot(mm, mm)
    radius_bound_numpy = np.trace(mm) ** (2 ** (-5))
    assert abs(radius_bound_numpy - radius_bound_theano) < tol

    # test the bound
    eigen_val = numpy.linalg.eig(m)
    assert (eigen_val[0].max() - radius_bound_theano) < tol

    # test type errors
    xx = theano.tensor.vector()
    ok = False
    try:
        spectral_radius_bound(xx, 5)
    except TypeError:
        ok = True
    assert ok
    ok = False
    try:
        spectral_radius_bound(x, 5.0)
    except TypeError:
        ok = True
    assert ok

    # test value error
    ok = False
    try:
        spectral_radius_bound(x, -5)
    except ValueError:
        ok = True
    assert ok


def test_transinv_to_invtrans():
    X = tensor.matrix("X")
    Y = tensor.nlinalg.matrix_inverse(X)
    Z = Y.transpose()
    f = theano.function([X], Z)
    if config.mode != "FAST_COMPILE":
        for node in f.maker.fgraph.toposort():
            if isinstance(node.op, MatrixInverse):
                assert isinstance(node.inputs[0].owner.op, DimShuffle)
            if isinstance(node.op, DimShuffle):
                assert node.inputs[0].name == "X"


def test_tag_solve_triangular():
    if not imported_scipy:
        pytest.skip("Scipy needed for the Cholesky op.")
    cholesky_lower = Cholesky(lower=True)
    cholesky_upper = Cholesky(lower=False)
    A = tensor.matrix("A")
    x = tensor.vector("x")
    L = cholesky_lower(A)
    U = cholesky_upper(A)
    b1 = solve(L, x)
    b2 = solve(U, x)
    f = theano.function([A, x], b1)
    if config.mode != "FAST_COMPILE":
        for node in f.maker.fgraph.toposort():
            if isinstance(node.op, Solve):
                assert node.op.A_structure == "lower_triangular"
    f = theano.function([A, x], b2)
    if config.mode != "FAST_COMPILE":
        for node in f.maker.fgraph.toposort():
            if isinstance(node.op, Solve):
                assert node.op.A_structure == "upper_triangular"


def test_matrix_inverse_solve():
    if not imported_scipy:
        pytest.skip("Scipy needed for the Solve op.")
    A = theano.tensor.dmatrix("A")
    b = theano.tensor.dmatrix("b")
    node = matrix_inverse(A).dot(b).owner
    [out] = inv_as_solve.transform(node)
    assert isinstance(out.owner.op, Solve)
