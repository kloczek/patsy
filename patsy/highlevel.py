# This file is part of Patsy
# Copyright (C) 2011 Nathaniel Smith <njs@pobox.com>
# See file COPYING for license information.

# These are made available in the patsy.* namespace:
__all__ = ["dmatrix", "dmatrices",
           "incr_dbuilder", "incr_dbuilders"]

# problems:
#   statsmodels reluctant to pass around separate eval environment, suggesting
#     that design_and_matrices-equivalent should return a formula_like
#   is ModelDesc really the high-level thing?
#   ModelDesign doesn't work -- need to work with the builder set
#   want to be able to return either a matrix or a pandas dataframe

import numpy as np
from patsy import PatsyError
from patsy.design_info import DesignMatrix, DesignInfo
from patsy.eval import EvalEnvironment
from patsy.desc import ModelDesc
from patsy.build import (design_matrix_builders,
                            build_design_matrices,
                            DesignMatrixBuilder)
from patsy.util import (have_pandas, asarray_or_pandas,
                           atleast_2d_column_default)

if have_pandas:
    import pandas

# Tries to build a (lhs, rhs) design given a formula_like and an incremental
# data source. If formula_like is not capable of doing this, then returns
# None.
def _try_incr_builders(formula_like, data_iter_maker, eval_env):
    if isinstance(formula_like, DesignMatrixBuilder):
        return (design_matrix_builders([[]], data_iter_maker)[0],
                formula_like)
    if (isinstance(formula_like, tuple)
        and len(formula_like) == 2
        and isinstance(formula_like[0], DesignMatrixBuilder)
        and isinstance(formula_like[1], DesignMatrixBuilder)):
        return formula_like
    if hasattr(formula_like, "__patsy_get_model_desc__"):
        formula_like = formula_like.__patsy_get_model_desc__(eval_env)
        if not isinstance(formula_like, ModelDesc):
            raise PatsyError("bad value from %r.__patsy_get_model_desc__"
                                % (formula_like,))
        # fallthrough
    if isinstance(formula_like, basestring):
        assert isinstance(eval_env, EvalEnvironment)
        formula_like = ModelDesc.from_formula(formula_like, eval_env)
        # fallthrough
    if isinstance(formula_like, ModelDesc):
        return design_matrix_builders([formula_like.lhs_termlist,
                                       formula_like.rhs_termlist],
                                      data_iter_maker)
    else:
        return None

def incr_dbuilder(formula_like, data_iter_maker, eval_env=0):
    """Construct a design matrix builder incrementally from a large data set.

    :arg formula_like: Similar to :func:`dmatrix`, except that explicit
      matrices are not allowed. Must be a formula string, a
      :class:`ModelDesc`, a :class:`DesignMatrixBuilder`, or an object with a
      ``__patsy_get_model_desc__`` method.
    :arg data_iter_maker: A zero-argument callable which returns an iterator
      over dict-like data objects. This must be a callable rather than a
      simple iterator because sufficiently complex formulas may require
      multiple passes over the data (e.g. if there are nested stateful
      transforms).
    :arg eval_env: Either a :class:`EvalEnvironment` which will be used to
      look up any variables referenced in `formula_like` that cannot be
      found in `data`, or else a depth represented as an
      integer which will be passed to :meth:`EvalEnvironment.capture`.
      ``eval_env=0`` means to use the context of the function calling
      :func:`incr_dbuilder` for lookups. If calling this function from a
      library, you probably want ``eval_env=1``, which means that variables
      should be resolved in *your* caller's namespace.
    :returns: A :class:`DesignMatrixBuilder`

    

    Tip: for `data_iter_maker`, write a generator like::

      def iter_maker():
          for data_chunk in my_data_store:
              yield data_chunk

    and pass `iter_maker`.
    """
    eval_env = EvalEnvironment.capture(eval_env, reference=1)
    builders = _try_incr_builders(formula_like, data_iter_maker, eval_env)
    if builders is None:
        raise PatsyError("bad formula-like object")
    if len(builders[0].design_info.column_names) > 0:
        raise PatsyError("encountered outcome variables for a model "
                            "that does not expect them")
    return builders[1]

def incr_dbuilders(formula_like, data_iter_maker, eval_env=0):
    """Construct two design matrix builders incrementally from a large data
    set.

    :func:`incr_dbuilders` is to :func:`incr_dbuilder` as :func:`dmatrices` is
    to :func:`dmatrix`. See :func:`incr_dbuilder` for details.
    """
    eval_env = EvalEnvironment.capture(eval_env, reference=1)
    builders = _try_incr_builders(formula_like, data_iter_maker, eval_env)
    if builders is None:
        raise PatsyError("bad formula-like object")
    if len(builders[0].design_info.column_names) == 0:
        raise PatsyError("model is missing required outcome variables")
    return builders

# This always returns a length-two tuple,
#   response, predictors
# where
#   response is a DesignMatrix (possibly with 0 columns)
#   predictors is a DesignMatrix
# The input 'formula_like' could be like:
#   (np.ndarray, np.ndarray)
#   (DesignMatrix, DesignMatrix)
#   (None, DesignMatrix)
#   np.ndarray  # for predictor-only models
#   DesignMatrix
#   (None, np.ndarray)
#   "y ~ x"
#   ModelDesc(...)
#   DesignMatrixBuilder
#   (DesignMatrixBuilder, DesignMatrixBuilder)
#   any object with a special method __patsy_get_model_desc__
def _do_highlevel_design(formula_like, data, eval_env,
                         NA_action, return_type):
    if return_type == "dataframe" and not have_pandas:
        raise PatsyError("pandas.DataFrame was requested, but pandas "
                            "is not installed")
    if return_type not in ("matrix", "dataframe"):
        raise PatsyError("unrecognized output type %r, should be "
                            "'matrix' or 'dataframe'" % (return_type,))
    def data_iter_maker():
        return iter([data])
    builders = _try_incr_builders(formula_like, data_iter_maker, eval_env)
    if builders is not None:
        return build_design_matrices(builders, data,
                                     NA_action=NA_action,
                                     return_type=return_type)
    else:
        # No builders, but maybe we can still get matrices
        if isinstance(formula_like, tuple):
            if len(formula_like) != 2:
                raise PatsyError("don't know what to do with a length %s "
                                    "matrices tuple"
                                    % (len(formula_like),))
            (lhs, rhs) = formula_like
        else:
            # subok=True is necessary here to allow DesignMatrixes to pass
            # through
            (lhs, rhs) = (None, asarray_or_pandas(formula_like, subok=True))
        # some sort of explicit matrix or matrices were given. Currently we
        # have them in one of these forms:
        #   -- an ndarray or subclass
        #   -- a DesignMatrix
        #   -- a pandas.Series
        #   -- a pandas.DataFrame
        # and we have to produce a standard output format.
        def _regularize_matrix(m, default_column_prefix):
            di = DesignInfo.from_array(m, default_column_prefix)
            if have_pandas and isinstance(m, (pandas.Series, pandas.DataFrame)):
                orig_index = m.index
            else:
                orig_index = None
            if return_type == "dataframe":
                m = atleast_2d_column_default(m, preserve_pandas=True)
                m = pandas.DataFrame(m)
                m.columns = di.column_names
                m.design_info = di
                return (m, orig_index)
            else:
                return (DesignMatrix(m, di), orig_index)
        rhs, rhs_orig_index = _regularize_matrix(rhs, "x")
        if lhs is None:
            lhs = np.zeros((rhs.shape[0], 0), dtype=float)
        lhs, lhs_orig_index = _regularize_matrix(lhs, "y")

        assert isinstance(getattr(lhs, "design_info", None), DesignInfo)
        assert isinstance(getattr(rhs, "design_info", None), DesignInfo)
        if lhs.shape[0] != rhs.shape[0]:
            raise PatsyError("shape mismatch: outcome matrix has %s rows, "
                                "predictor matrix has %s rows"
                                % (lhs.shape[0], rhs.shape[0]))
        if rhs_orig_index is not None and lhs_orig_index is not None:
            if not rhs_orig_index.equals(lhs_orig_index):
                raise PatsyError("index mismatch: outcome and "
                                    "predictor have incompatible indexes")
        if return_type == "dataframe":
            if rhs_orig_index is not None and lhs_orig_index is None:
                lhs.index = rhs.index
            if rhs_orig_index is None and lhs_orig_index is not None:
                rhs.index = lhs.index
        return (lhs, rhs)

def dmatrix(formula_like, data={}, eval_env=0,
            NA_action="drop", return_type="matrix"):
    """Construct a single design matrix given a formula_like and data.

    :arg formula_like: An object that can be used to construct a design
      matrix. See below.
    :arg data: A dict-like object that can be used to look up variables
      referenced in `formula_like`.
    :arg eval_env: Either a :class:`EvalEnvironment` which will be used to
      look up any variables referenced in `formula_like` that cannot be
      found in `data`, or else a depth represented as an
      integer which will be passed to :meth:`EvalEnvironment.capture`.
      ``eval_env=0`` means to use the context of the function calling
      :func:`dmatrix` for lookups. If calling this function from a library,
      you probably want ``eval_env=1``, which means that variables should be
      resolved in *your* caller's namespace.
    :arg NA_action: What to do with rows that contain missing values. Either
      ``"drop"``, ``"raise"``, or an :class:`NAAction` object. See
      :class:`NAAction` for details on what values count as 'missing' (and how
      to alter this).
    :arg return_type: Either ``"matrix"`` or ``"dataframe"``. See below.

    The `formula_like` can take a variety of forms:

    * A formula string like "x1 + x2" (for :func:`dmatrix`) or "y ~ x1 + x2"
      (for :func:`dmatrices`). For details see :ref:`formulas`.
    * A :class:`ModelDesc`, which is a Python object representation of a
      formula. See :ref:`formulas` and :ref:`expert-model-specification` for
      details.
    * A :class:`DesignMatrixBuilder`.
    * An object that has a method called :meth:`__patsy_get_model_desc__`.
      For details see :ref:`expert-model-specification`.
    * A numpy array_like (for :func:`dmatrix`) or a tuple
      (array_like, array_like) (for :func:`dmatrices`). These will have
      metadata added, representation normalized, and then be returned
      directly. In this case `data` and `eval_env` are
      ignored. There is special handling for two cases:

      * :class:`DesignMatrix` objects will have their :class:`DesignInfo`
        preserved. This allows you to set up custom column names and term
        information even if you aren't using the rest of the patsy
        machinery.
      * :class:`pandas.DataFrame` or :class:`pandas.Series` objects will have
        their (row) indexes checked. If two are passed in, their indexes must
        be aligned. If ``return_type="dataframe"``, then their indexes will be
        preserved on the output.
      
    Regardless of the input, the return type is always either:

    * A :class:`DesignMatrix`, if ``return_type="matrix"`` (the default)
    * A :class:`pandas.DataFrame`, if ``return_type="dataframe"``.

    The actual contents of the design matrix is identical in both cases, and
    in both cases a :class:`DesignInfo` will be available in a
    ``.design_info`` attribute on the return value. However, for
    ``return_type="dataframe"``, any pandas indexes on the input (either in
    `data` or directly passed through `formula_like`) will be
    preserved, which may be useful for e.g. time-series models.
    """
    eval_env = EvalEnvironment.capture(eval_env, reference=1)
    (lhs, rhs) = _do_highlevel_design(formula_like, data, eval_env,
                                      NA_action, return_type)
    if lhs.shape[1] != 0:
        raise PatsyError("encountered outcome variables for a model "
                            "that does not expect them")
    return rhs

def dmatrices(formula_like, data={}, eval_env=0,
              NA_action="drop", return_type="matrix"):
    """Construct two design matrices given a formula_like and data.

    This function is identical to :func:`dmatrix`, except that it requires
    (and returns) two matrices instead of one. By convention, the first matrix
    is the "outcome" or "y" data, and the second is the "predictor" or "x"
    data.

    
    it requires the
    formula to specify both a left-hand side outcome matrix and a right-hand
    side predictors matrix, which are returned as a tuple.

    See :func:`dmatrix` for details.
    """
    eval_env = EvalEnvironment.capture(eval_env, reference=1)
    (lhs, rhs) = _do_highlevel_design(formula_like, data, eval_env,
                                      NA_action, return_type)
    if lhs.shape[1] == 0:
        raise PatsyError("model is missing required outcome variables")
    return (lhs, rhs)
