"""Retain declared test periods with zero original observations.

This is an aggregation repair only. Labels, scores, predictions, original
event identities, and acceptance gates are unchanged. Repeated observed-row
boundaries represent empty declared periods; they do not invent observations.
An empty period is unmeasurable under the existing comparison and gates.
"""
from __future__ import annotations

import numpy as np
from sparse_evaluation import compare_sparse, _slots
from evaluation import gates


def assess_sparse_series_allow_empty(labels, baseline_prediction,
                                     candidate_prediction, slots, boundaries,
                                     sample_seconds=900):
    """Evaluate all declared periods, including empty observed-row slices.

    ``boundaries`` covers the entire original observed-row axis exactly once
    in nondecreasing integer order. A repeated boundary keeps an empty period
    in the returned period list. Pooled event identities are computed once on
    the complete original axis before slicing, including events that span a
    missing time interval. Existing sparse metrics require a consecutive-slot
    observed0-to-alarm1 transition to confirm a new detection.
    """
    y=np.asarray(labels);b=np.asarray(baseline_prediction)
    c=np.asarray(candidate_prediction);s=_slots(slots,len(y))
    bounds=np.asarray(boundaries)
    if (bounds.ndim!=1 or bounds.dtype.kind not in "iu" or len(bounds)<2
        or bounds[0]!=0 or bounds[-1]!=len(y)
        or np.any(bounds[1:]<bounds[:-1])):
        raise ValueError("boundaries must cover observed rows exactly once in nondecreasing integer order")
    whole=compare_sparse(y,b,c,s,sample_seconds)
    periods=[compare_sparse(y[a:z],b[a:z],c[a:z],s[a:z],sample_seconds)
             for a,z in zip(bounds[:-1],bounds[1:])]
    return {"pooled":whole,"periods":periods,"gates":gates(periods,[whole])}
